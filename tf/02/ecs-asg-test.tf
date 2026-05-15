variable "test_instance_type" {
  description = "EC2 instance type for test/dev workers"
  type        = string
  default     = "t3.medium"
}

# ---------------------------------------------------------------------------
# Test (small CPU, cheap, for dev/smoke testing)
# ---------------------------------------------------------------------------

resource "aws_launch_template" "test" {
  name_prefix   = join("-", [var.org_name, var.project_name, var.env, "test-"])
  image_id      = data.aws_ssm_parameter.ecs_cpu_ami.value
  instance_type = var.test_instance_type

  iam_instance_profile { arn = aws_iam_instance_profile.gpu.arn }
  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.gpu.id]
  }
  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo ECS_CLUSTER=${module.ecs.cluster_name} >> /etc/ecs/ecs.config
  EOT
  )
  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.project_tags, { Name = join("-", [var.org_name, var.project_name, var.env, "test-worker"]) })
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_autoscaling_group" "test" {
  name                = join("-", [var.org_name, var.project_name, var.env, "test-asg"])
  min_size            = 2
  desired_capacity    = 2
  max_size            = 8
  vpc_zone_identifier = [for s in data.aws_subnet.private_subnets : s.id]

  launch_template {
    id      = aws_launch_template.test.id
    version = "$Latest"
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
