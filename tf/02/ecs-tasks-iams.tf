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
      "arn:aws:sqs:${var.region}:${data.aws_caller_identity.current.account_id}:${var.org_name}-${var.project_name}-${var.env}-*",
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

  statement {
    sid       = "LifecyclePublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.lifecycle.arn]
  }
}

resource "aws_iam_role_policy" "model_task" {
  name   = join("-", [var.project_name, var.env, "ecs-task-policy"])
  role   = aws_iam_role.model_task.id
  policy = data.aws_iam_policy_document.model_task.json
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "efs_mount_point" {
  description = "location to mount the efs disk for correct path access"
  value       = var.efs_mount_point
}

output "efs_model_cache_path" {
  description = "Container-relative path where HuggingFace model weights are cached on EFS."
  value       = var.efs_model_cache_path
}
