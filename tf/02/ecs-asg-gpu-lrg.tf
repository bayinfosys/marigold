# ---------------------------------------------------------------------------
# gpu-lrg  (g5 family, A10G)
#
# g5.48xlarge  -- 8x A10G, 192GB VRAM  -- primary, large model work
# g5.12xlarge  -- 4x A10G, 96GB VRAM   -- fallback
#
# On-demand only. Spot availability for g5.48xlarge in eu-west-2 is thin.
# on_demand_base_capacity = 2 ensures both desired instances are on-demand.
# ---------------------------------------------------------------------------

resource "aws_launch_template" "gpu_lrg" {
  name_prefix = join("-", [var.org_name, var.project_name, var.env, "gpu-lrg-"])
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
      Name = join("-", [var.org_name, var.project_name, var.env, "gpu-lrg-worker"])
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "gpu_lrg" {
  name                = join("-", [var.org_name, var.project_name, var.env, "gpu-lrg-asg"])
  min_size            = 0
  desired_capacity    = 0
  max_size            = 10
  vpc_zone_identifier = [for s in data.aws_subnet.private_subnets : s.id]

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 1
      on_demand_percentage_above_base_capacity = 100
      on_demand_allocation_strategy            = "lowest-price"
      spot_allocation_strategy                 = "price-capacity-optimized"
    }

    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.gpu_lrg.id
        version            = "$Latest"
      }

#      override {
#        instance_type = "g5.48xlarge"
#      }
      override {
        instance_type = "g5.12xlarge"
      }
      override {
        instance_type = "g5.8xlarge"
      }
      override {
        instance_type = "g5.4xlarge"
      }
#      override {
#        instance_type = "g5.2xlarge"
#      }
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
}
