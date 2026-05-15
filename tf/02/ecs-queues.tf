# ---------------------------------------------------------------------------
# Per-model SQS queues and CloudWatch log groups.
#
# One queue and one log group per model declared in models.yaml.
# The queue URL is passed to the task as AWS_SQS_MODEL_QUEUE.
# The log group name is referenced by the task's logConfiguration.
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "model_queues" {
  for_each = var.models

  name = join("-", [var.org_name, var.project_name, var.env, each.key, "queue"])

  message_retention_seconds  = 3600
  visibility_timeout_seconds = each.value.timeout

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.model_dlq[each.key].arn
    maxReceiveCount     = 3
  })

  tags = var.project_tags
}

resource "aws_sqs_queue" "model_dlq" {
  for_each                  = var.models
  name                      = join("-", [var.org_name, var.project_name, var.env, each.key, "dlq"])
  message_retention_seconds = 86400
}

resource "aws_cloudwatch_log_group" "ecs_model_logs" {
  for_each = var.models

  name              = join("-", [var.org_name, var.project_name, var.env, "models", each.key])
  retention_in_days = 5

  tags = var.project_tags
}
