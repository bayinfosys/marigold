# SQS queue to buffer REQUEST_QUEUED events from SNS to task_queuer
# Otherwise SNS will drop messages while the lambda pool is scaling
resource "aws_sqs_queue" "task_queuer_events" {
  name                       = join("-", [var.org_name, var.project_name, var.env, "task-queuer-events"])
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.task_queuer_events_dlq.arn
    maxReceiveCount     = 3
  })

  tags = var.project_tags
}

resource "aws_sqs_queue" "task_queuer_events_dlq" {
  name                      = join("-", [var.org_name, var.project_name, var.env, "task-queuer-events-dlq"])
  message_retention_seconds = 86400
  tags                      = var.project_tags
}

resource "aws_sqs_queue_policy" "task_queuer_events_sns" {
  queue_url = aws_sqs_queue.task_queuer_events.url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSNSPublish"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.task_queuer_events.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_sns_topic.lifecycle.arn }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "task_queuer" {
  topic_arn = aws_sns_topic.lifecycle.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.task_queuer_events.arn

  filter_policy_scope = "MessageAttributes"
  filter_policy = jsonencode({
    event_type = [local.sns_event_types.REQUEST_QUEUED]
  })
}

module "task_queuer_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "task-queuer"])
  description                       = "Receives REQUEST_QUEUED events, launches ECS tasks"
  hash_extra                        = "task-queuer"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.task_queuer.handler"

  reserved_concurrent_executions = 1

  environment_variables = {
    AWS_S3_ASSETS_BUCKET_NAME = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT   = aws_s3_object.models_config_internal.key
    LIFECYCLE_TOPIC_ARN       = aws_sns_topic.lifecycle.arn
    LAUNCH_QUEUE_URL          = aws_sqs_queue.task_launch_queue.url
    BUILD_VERSION             = var.git_tag
    DEFAULT_MAX_WORKERS       = "4"
    LAUNCH_DEDUP_WINDOW_S     = "30"
    ECS_CLUSTER_ARN           = module.ecs.cluster_arn
  }

  policy_statements = {
    s3_read = {
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        aws_s3_object.models_config_internal.arn,
      ]
    }

    sns_publish = {
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.lifecycle.arn]
    }

    sqs_stats = {
      effect    = "Allow"
      actions   = ["sqs:GetQueueAttributes"]
      resources = ["arn:aws:sqs:${var.region}:${data.aws_caller_identity.current.account_id}:${var.org_name}-${var.project_name}-${var.env}-*"]
    }

    sqs_task_launch_enqueue = {
      effect    = "Allow"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.task_launch_queue.arn]
    }

    sqs_consume_events = {
      effect = "Allow"
      actions = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility",
      ]
      resources = [aws_sqs_queue.task_queuer_events.arn]
    }

    ecs_list_tasks = {
      effect    = "Allow"
      actions   = ["ecs:ListTasks"]
      resources = ["*"]
    }

    ecs_update_service = {
      effect    = "Allow"
      actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
      resources = ["arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${module.ecs.cluster_name}/*"]
    }

  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_event_source_mapping" "task_queuer_sqs" {
  event_source_arn = aws_sqs_queue.task_queuer_events.arn
  function_name    = module.task_queuer_lambda.lambda_function_arn
  batch_size       = 1
  enabled          = true
}
