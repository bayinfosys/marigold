# ---------------------------------------------------------------------------
# ECS cluster, task IAM role, and capacity provider configuration.
#
# Capacity providers:
#   EC2           -- CPU (default)
#   gpu           -- EC2 GPU instances via ASG (see ecs-gpu.tf)
#                    min_size=0, desired_capacity=0 until GPU tasks are needed
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ECS cluster
# ---------------------------------------------------------------------------

module "ecs" {
  source       = "terraform-aws-modules/ecs/aws"
  version      = "~> 7.5"
  cluster_name = join("-", [var.org_name, var.project_name, var.env, "inference"])

  create_task_exec_iam_role = true
  create_task_exec_policy   = true

  cluster_capacity_providers = [
    var.capacity_provider_big_cpu,
    var.capacity_provider_gpu_sm,
    var.capacity_provider_gpu_lrg,
    "anonchat",
  ]

  capacity_providers = {
    (var.capacity_provider_gpu_sm) = {
      auto_scaling_group_provider = {
        auto_scaling_group_arn         = aws_autoscaling_group.gpu_sm.arn
        managed_termination_protection = "DISABLED"
        managed_scaling = {
          status                    = "ENABLED"
          target_capacity           = 80
          minimum_scaling_step_size = 1
          maximum_scaling_step_size = 2
          instance_warmup_period    = 300
        }
      }
    }
    (var.capacity_provider_gpu_lrg) = {
      auto_scaling_group_provider = {
        auto_scaling_group_arn         = aws_autoscaling_group.gpu_lrg.arn
        managed_termination_protection = "DISABLED"
        managed_scaling = {
          status                    = "ENABLED"
          target_capacity           = 80
          minimum_scaling_step_size = 1
          maximum_scaling_step_size = 1
          instance_warmup_period    = 420
        }
      }
    }
    anonchat = {
      auto_scaling_group_provider = {
        auto_scaling_group_arn         = aws_autoscaling_group.anonchat.arn
        managed_termination_protection = "DISABLED"
        managed_scaling = {
          status                    = "ENABLED"
          target_capacity           = 80
          minimum_scaling_step_size = 1
          maximum_scaling_step_size = 1
          instance_warmup_period    = 300
        }
      }
    }
    (var.capacity_provider_big_cpu) = {
      auto_scaling_group_provider = {
        auto_scaling_group_arn         = aws_autoscaling_group.big_cpu.arn
        managed_termination_protection = "DISABLED"
        managed_scaling = {
          status                    = "ENABLED"
          target_capacity           = 80
          minimum_scaling_step_size = 1
          maximum_scaling_step_size = 2
          instance_warmup_period    = 120
        }
      }
    }
  }

  default_capacity_provider_strategy = {
    (var.capacity_provider_big_cpu) = {
      weight = 1
      base   = 1
    }
  }

  tags = var.project_tags
}
