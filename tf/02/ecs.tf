# ---------------------------------------------------------------------------
# ECS cluster, task IAM role, and capacity provider configuration.
#
# Capacity providers:
#   EC2           -- CPU (default)
#   gpu           -- EC2 GPU instances via ASG (see ecs-gpu.tf)
#                    min_size=0, desired_capacity=0 until GPU tasks are needed
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Task IAM role
# This is the role assumed by running containers (not the execution role).
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "model_task_assume_role" {
  statement {
    sid     = "ECSServiceAssumeRole"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com", "ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "model_task" {
  name                  = join("-", [var.project_name, var.env, "ecs-model-task"])
  assume_role_policy    = data.aws_iam_policy_document.model_task_assume_role.json
  force_detach_policies = true
  tags                  = var.project_tags
}

data "aws_iam_policy_document" "model_task" {
  statement {
    sid     = "WorkQueuePermissions"
    effect  = "Allow"
    actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [
      "arn:aws:sqs:${var.region}:${data.aws_caller_identity.current.account_id}:${var.org_name}-${var.project_name}-${var.env}-*-queue",
      aws_sqs_queue.anonchat_queue.arn,
    ]
  }

  statement {
    sid       = "UsageTablePermissions"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [module.usage_table.dynamodb_table_arn]
  }

  statement {
    sid    = "ResultsCachePermissions"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem",
    ]
    resources = [aws_dynamodb_table.results_cache.arn]
  }

  statement {
    sid       = "WorkflowStepsPermissions"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.workflow_steps.arn]
  }

  statement {
    sid       = "EFSPermissions"
    effect    = "Allow"
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientRead"]
    resources = [data.aws_efs_access_point.efs_assets_ro.arn]
  }

  statement {
    sid       = "CloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }

  statement {
    sid       = "ModelOutputsWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.model_outputs.arn}/outputs/*"]
  }
}

resource "aws_iam_role_policy" "model_task" {
  name   = join("-", [var.project_name, var.env, "ecs-task-policy"])
  role   = aws_iam_role.model_task.id
  policy = data.aws_iam_policy_document.model_task.json
}

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
