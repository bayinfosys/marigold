# ---------------------------------------------------------------------------
# Launch FIFO queue
#
# Buffers run_task requests from task_runner.
# FIFO with content-based deduplication disabled -- task_runner sets
# explicit MessageDeduplicationId per model per time bucket.
# One MessageGroup per model_hash ensures ordered delivery per model.
#
# Visibility timeout matches the Lambda timeout to prevent duplicate
# processing if the Lambda is slow to respond.
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "task_launch_queue" {
  name                       = join("-", [var.org_name, var.project_name, var.env, "task-launch-queue"])
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.task_launch_dlq.arn
    maxReceiveCount     = 3
  })

  tags = var.project_tags
}

resource "aws_sqs_queue" "task_launch_dlq" {
  name                      = join("-", [var.org_name, var.project_name, var.env, "task-launch-dlq"])
  message_retention_seconds = 86400
  tags                      = var.project_tags
}


# ---------------------------------------------------------------------------
# Launcher Lambda
# ---------------------------------------------------------------------------

module "task_launcher_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "task-launcher"])
  description                       = "Drains task_launch queue, calls ECS run_task. Rate-limited by SQS visibility timeout on provisioning limit errors."
  hash_extra                        = "task-launcher"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime
  timeout                           = 30

  reserved_concurrent_executions    = 1

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.task_launcher.handler"

  environment_variables = {
    ECS_CLUSTER_ARN               = module.ecs.cluster_arn
    ECS_SUBNETS                   = join(",", [for x in data.aws_subnet.private_subnets : x.id])
    ECS_SECURITY_GROUPS           = join(",", [data.aws_security_group.lambda_sg.id])
    AWS_S3_ASSETS_BUCKET_NAME     = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT       = aws_s3_object.models_config_internal.key
    ECS_CAPACITY_PROVIDER_GPU_SM  = var.capacity_provider_gpu_sm
    ECS_CAPACITY_PROVIDER_GPU_LRG = var.capacity_provider_gpu_lrg
    ECS_CAPACITY_PROVIDER_BIG_CPU = var.capacity_provider_big_cpu
    DEFAULT_MAX_WORKERS           = "4"
    BUILD_VERSION                 = var.git_tag
  }

  policy_statements = {
    ecs_list_tasks = {
      effect    = "Allow"
      actions   = ["ecs:ListTasks"]
      resources = ["*"]
    }

    ecs_run_task = {
      effect  = "Allow"
      actions = ["ecs:RunTask"]
      resources = [
        "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project_name}-${var.env}-*",
        "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/*",
      ]
    }

    ecs_pass_role = {
      effect  = "Allow"
      actions = ["iam:PassRole"]
      resources = [
        aws_iam_role.model_task.arn,
        module.ecs.task_exec_iam_role_arn,
      ]
    }

    s3_read = {
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = [aws_s3_object.models_config_internal.arn]
    }

    sqs_task_launch_queue = {
      effect  = "Allow"
      actions = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility",
      ]
      resources = [aws_sqs_queue.task_launch_queue.arn]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_event_source_mapping" "task_launcher_sqs" {
  event_source_arn = aws_sqs_queue.task_launch_queue.arn
  function_name    = module.task_launcher_lambda.lambda_function_arn
  batch_size       = 1   # one launch decision per invocation -- avoids race on active count
  enabled          = true
}
