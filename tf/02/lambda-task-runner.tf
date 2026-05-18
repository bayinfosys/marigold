resource "aws_sns_topic" "lifecycle" {
  name = join("-", [var.org_name, var.project_name, var.env, "lifecycle"])
  tags = var.project_tags
}

module "task_runner_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "task-runner"])
  description                       = "Receives REQUEST_QUEUED events, launches ECS tasks"
  hash_extra                        = "task-runner"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime

  reserved_concurrent_executions = 1

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.task_runner.handler"

  environment_variables = {
    ECS_CLUSTER_ARN               = module.ecs.cluster_arn
    ECS_SUBNETS                   = join(",", [for x in data.aws_subnet.private_subnets : x.id])
    ECS_SECURITY_GROUPS           = join(",", [data.aws_security_group.lambda_sg.id])
    AWS_S3_ASSETS_BUCKET_NAME     = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT       = aws_s3_object.models_config_internal.key
    ECS_CAPACITY_PROVIDER_GPU_SM  = var.capacity_provider_gpu_sm
    ECS_CAPACITY_PROVIDER_GPU_LRG = var.capacity_provider_gpu_lrg
    ECS_CAPACITY_PROVIDER_BIG_CPU = var.capacity_provider_big_cpu
    LIFECYCLE_TOPIC_ARN           = aws_sns_topic.lifecycle.arn
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
        "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/vecmdl-${var.env}-*",
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
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_permission" "sns_invoke_task_runner" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.task_runner_lambda.lambda_function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.lifecycle.arn
}

resource "aws_sns_topic_subscription" "task_runner" {
  topic_arn = aws_sns_topic.lifecycle.arn
  protocol  = "lambda"
  endpoint  = module.task_runner_lambda.lambda_function_arn

  filter_policy = jsonencode({
    event_type = [local.sns_event_types.REQUEST_QUEUED]
  })
}
