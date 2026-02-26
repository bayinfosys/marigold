# ---------------------------------------------------------------------------
# ECS cluster, task IAM role, and capacity provider configuration.
#
# Capacity providers:
#   FARGATE       -- serverless CPU (default)
#   FARGATE_SPOT  -- serverless CPU spot (cost-optimised)
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
    sid       = "WorkQueuePermissions"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage"]
    resources = [for x in aws_sqs_queue.model_queues : x.arn]
  }

  statement {
    sid       = "UsageTablePermissions"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [module.usage_table.dynamodb_table_arn]
  }

  statement {
    sid       = "ResultsCachePermissions"
    effect    = "Allow"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.results_cache.arn]
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
  cluster_name = join("-", [var.project_name, var.env, "fargate-cluster"])

  create_task_exec_iam_role = true
  create_task_exec_policy   = true

  cluster_capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy = {
    FARGATE = {
      default_capacity_provider_strategy = {
        weight = 50
        base   = 20
      }
    }
    FARGATE_SPOT = {
      default_capacity_provider_strategy = {
        weight = 50
      }
    }
  }

  autoscaling_capacity_providers = {
    gpu = {
      auto_scaling_group_arn         = aws_autoscaling_group.gpu.arn
      managed_termination_protection = "DISABLED"

      managed_scaling = {
        status          = "ENABLED"
        target_capacity = 100
      }

      # weight=0 means no tasks are scheduled here by default.
      # To route tasks to GPU, add a capacity_provider_strategy block
      # to the relevant task definition and increase weight.
      default_capacity_provider_strategy = {
        weight = 0
        base   = 0
      }
    }
  }

  tags = var.project_tags
}
