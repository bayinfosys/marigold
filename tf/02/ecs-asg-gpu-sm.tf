# ---------------------------------------------------------------------------
# EC2 capacity providers for ECS.
#
# gpu-sm  -- g4dn.xlarge  (T4, 16GB VRAM)   small GPU work, instruct models up to ~13B
# gpu-lrg -- g5.12xlarge  (4x A10G, 96GB)   large GPU work, 32B+ models, image gen
#
# Both use Spot pricing. The queue-based architecture handles interruptions
# cleanly -- interrupted tasks reappear in SQS after visibility timeout expires.
#
# Mixed instances policy on each ASG allows fallback to similar instance types
# within the same GPU family if the primary choice has no spot capacity in an AZ.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared IAM
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "gpu_instance_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gpu_instance" {
  name               = join("-", [var.org_name, var.project_name, var.env, "gpu-instance"])
  assume_role_policy = data.aws_iam_policy_document.gpu_instance_assume_role.json
  tags               = var.project_tags
}

resource "aws_iam_role_policy_attachment" "gpu_ecs_agent" {
  role       = aws_iam_role.gpu_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "gpu_ssm" {
  role       = aws_iam_role.gpu_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "gpu" {
  name = join("-", [var.org_name, var.project_name, var.env, "gpu-instance-profile"])
  role = aws_iam_role.gpu_instance.name
  tags = var.project_tags
}


# ---------------------------------------------------------------------------
# Shared security group
# ---------------------------------------------------------------------------

resource "aws_security_group" "gpu" {
  name        = join("-", [var.org_name, var.project_name, var.env, "gpu-sg"])
  description = "GPU ECS instances -- egress only"
  vpc_id      = data.aws_vpc.vpc.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "allow all outbound"
  }

  tags = var.project_tags
}


# ---------------------------------------------------------------------------
# AMI
# ---------------------------------------------------------------------------

data "aws_ssm_parameter" "ecs_gpu_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id"
}


# ---------------------------------------------------------------------------
# gpu-sm  (g4dn family, T4 16GB)
# ---------------------------------------------------------------------------

resource "aws_launch_template" "gpu_sm" {
  name_prefix = join("-", [var.org_name, var.project_name, var.env, "gpu-sm-"])
  image_id    = data.aws_ssm_parameter.ecs_gpu_ami.value

  iam_instance_profile {
    arn = aws_iam_instance_profile.gpu.arn
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.gpu.id]
  }

  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo ECS_CLUSTER=${module.ecs.cluster_name} >> /etc/ecs/ecs.config
    echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.project_tags, {
      Name = join("-", [var.org_name, var.project_name, var.env, "gpu-sm-worker"])
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "gpu_sm" {
  name                = join("-", [var.org_name, var.project_name, var.env, "gpu-sm-asg"])
  min_size            = 1
  desired_capacity    = 3
  max_size            = 20
  vpc_zone_identifier = [for s in data.aws_subnet.private_subnets : s.id]
  capacity_rebalance  = true

  mixed_instances_policy {
    instances_distribution {
      on_demand_allocation_strategy            = "lowest-price"
      on_demand_base_capacity                  = 1
      on_demand_percentage_above_base_capacity = 20
      spot_allocation_strategy                 = "price-capacity-optimized"
    }

    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.gpu_sm.id
        version            = "$Latest"
      }

      override {
        instance_requirements {
          accelerator_count { min = 1 }
          accelerator_names         = ["t4"]
          accelerator_manufacturers = ["nvidia"]
          accelerator_types         = ["gpu"]
          vcpu_count {
            min = 8
            max = 32
          }
          memory_mib {
            min = 28000
            max = 70000
          }
        }
      }
    }
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = true
    propagate_at_launch = true
  }

  dynamic "tag" {
    for_each = var.project_tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    ignore_changes = [desired_capacity]
  }
}
