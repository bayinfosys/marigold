# ---------------------------------------------------------------------------
# GPU capacity provider for ECS.
#
# Uses EC2 instances with NVIDIA GPUs (g4dn family by default) running the
# ECS-optimised Amazon Linux 2023 GPU AMI.
#
# The ASG starts at zero. To activate:
#   1. Set desired_capacity > 0, or enable managed scaling target.
#   2. Add a capacity_provider_strategy to the relevant task definitions
#      in ecs-tasks.tf referencing the "gpu" capacity provider.
#   3. Update requires_compatibilities to ["EC2"] for those tasks.
#
# The capacity provider is registered with the cluster via the
# autoscaling_capacity_providers input in ecs.tf.
# ---------------------------------------------------------------------------

variable "gpu_instance_type" {
  description = "EC2 instance type for GPU workers"
  type        = string
  default     = "g4dn.xlarge"
}

# ECS-optimised GPU AMI -- Amazon Linux 2023, kept current via SSM parameter.
data "aws_ssm_parameter" "ecs_gpu_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id"
}

# ---------------------------------------------------------------------------
# IAM instance profile
# EC2 instances in an ECS cluster need the container service role to register
# with the cluster and pull images from ECR.
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

# ---------------------------------------------------------------------------
# Security group
# GPU instances need egress for ECR pulls, EFS, and SSM.
# Ingress is not required -- tasks are dispatched via SQS, not direct connections.
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Launch template
# Registers the instance with the ECS cluster on startup via user_data.
# ---------------------------------------------------------------------------

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

  # Register with the ECS cluster and configure the Docker daemon for GPU support.
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

# ---------------------------------------------------------------------------
# Auto-scaling group
# Starts at zero. Managed scaling via the ECS capacity provider will scale
# up when GPU tasks are queued and weight > 0 in the capacity provider strategy.
# ---------------------------------------------------------------------------

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

  # Required for ECS managed scaling to function correctly.
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
