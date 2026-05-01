# ---------------------------------------------------------------------------
# EC2 capacity provider for ECS.
#
# Used for GPU model workers (g4dn family) and any future EC2-backed tasks.
# The ASG starts at zero. Managed scaling via the ECS capacity provider
# scales up when EC2 tasks are queued.
#
# To activate GPU workers:
#   1. In ecs-services.tf, remove launch_type = "FARGATE" from
#      model_services_gpu and uncomment the capacity_provider_strategy block.
#   2. Update requires_compatibilities to ["EC2"] in ecs-tasks.tf for GPU models.
#   3. Ensure the capacity provider is registered with the cluster in ecs.tf.
# ---------------------------------------------------------------------------

variable "gpu_instance_type" {
  description = "EC2 instance type for GPU workers"
  type        = string
  default     = "g4dn.xlarge"
}

data "aws_ssm_parameter" "ecs_gpu_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id"
}

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
  name               = join("-", [var.project_name, var.env, "gpu-instance"])
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
  name = join("-", [var.project_name, var.env, "gpu-instance-profile"])
  role = aws_iam_role.gpu_instance.name
  tags = var.project_tags
}

resource "aws_security_group" "gpu" {
  name        = join("-", [var.project_name, var.env, "gpu-sg"])
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

resource "aws_launch_template" "gpu" {
  name_prefix   = join("-", [var.project_name, var.env, "gpu-"])
  image_id      = data.aws_ssm_parameter.ecs_gpu_ami.value
  instance_type = var.gpu_instance_type

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
      Name = join("-", [var.project_name, var.env, "gpu-worker"])
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "gpu" {
  name                = join("-", [var.project_name, var.env, "gpu-asg"])
  min_size            = 0
  desired_capacity    = 0
  max_size            = 4
  vpc_zone_identifier = [for s in data.aws_subnet.private_subnets : s.id]

  launch_template {
    id      = aws_launch_template.gpu.id
    version = "$Latest"
  }

  protect_from_scale_in = true

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
}
