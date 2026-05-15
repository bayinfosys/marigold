# ---------------------------------------------------------------------------
# anonchat capacity provider
#
# Dedicated always-on g4dn.xlarge for the public anon chat page.
# min_size=1 keeps one instance warm at all times -- this is marketing
# budget, not inference workload. Separate from the general gpu-sm pool
# so chat availability is never affected by inference load.
# ---------------------------------------------------------------------------

resource "aws_launch_template" "anonchat" {
  name_prefix   = join("-", [var.org_name, var.project_name, var.env, "anonchat-"])
  image_id      = data.aws_ssm_parameter.ecs_gpu_ami.value
  instance_type = "g4dn.2xlarge"

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
      Name = join("-", [var.org_name, var.project_name, var.env, "anonchat"])
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "anonchat" {
  name                  = join("-", [var.org_name, var.project_name, var.env, "anonchat-asg"])
  min_size              = 2
  desired_capacity      = 2
  max_size              = 20
  vpc_zone_identifier   = [for s in data.aws_subnet.private_subnets : s.id]

  launch_template {
    id      = aws_launch_template.anonchat.id
    version = "$Latest"
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = true
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity]
  }
}
