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

  message_retention_seconds  = 86400    # 24 hours wait on the queue before we fail
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

# ---------------------------------------------------------------------------
# SNS -> SQS subscriptions, one per model.
#
# Each queue receives REQUEST_QUEUED events for its model only.
# raw_message_delivery = true: the worker receives the MarigoldSQSMessage
# JSON body directly with no SNS envelope, matching the existing
# worker.py get_message parser without modification.
#
# filter_policy_scope = "MessageAttributes" is required when filtering
# on message attributes rather than the message body.
# ---------------------------------------------------------------------------

resource "aws_sns_topic_subscription" "model_queue_feed" {
  for_each = var.models

  topic_arn = aws_sns_topic.lifecycle.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.model_queues[each.key].arn

  raw_message_delivery = true

  filter_policy_scope = "MessageAttributes"
  filter_policy = jsonencode({
    event_type = [local.sns_event_types.REQUEST_QUEUED]
    model_name = [each.value.environment_variables["MODELNAME"]]
  })
}

# Allow SNS to write to each model queue.
resource "aws_sqs_queue_policy" "model_queue_sns" {
  for_each  = var.models
  queue_url = aws_sqs_queue.model_queues[each.key].url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSNSPublish"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.model_queues[each.key].arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_sns_topic.lifecycle.arn
        }
      }
    }]
  })
}
