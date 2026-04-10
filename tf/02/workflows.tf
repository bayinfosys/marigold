# ---------------------------------------------------------------------------
# Workflow feature infrastructure
#
# DynamoDB tables:    workflow_templates, workflow_state, workflow_steps,
#                     workflow_tasks (runfox SQSRunner internal state)
# SQS queue:         dummy model queue
# Lambda functions:  workflow_api, workflow_executor,
#                    workflow_stream_handler, workflow_dummy_model
# Event source:      DynamoDB Streams on workflow_steps -> stream_handler
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DynamoDB tables
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "workflow_templates" {
  name         = join("-", [var.org_name, var.project_name, var.env, "workflow-templates"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  tags = var.project_tags
}

resource "aws_dynamodb_table" "workflow_state" {
  name         = join("-", [var.org_name, var.project_name, var.env, "workflow-state"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  tags = var.project_tags
}

resource "aws_dynamodb_table" "workflow_steps" {
  name         = join("-", [var.org_name, var.project_name, var.env, "workflow-steps"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # Streams feed completed step records to the stream handler Lambda.
  # NEW_IMAGE only: the handler reads current attribute values directly
  # from the stream record and does not need the prior image.
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.project_tags
}

resource "aws_dynamodb_table" "workflow_tasks" {
  # runfox SQSRunner internal state. One item per dispatched step.
  # Written by dispatch(), never read in the event-driven Marigold path.
  # Retained for runfox internal consistency and diagnostics.
  name         = join("-", [var.org_name, var.project_name, var.env, "workflow-tasks"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.project_tags
}


# ---------------------------------------------------------------------------
# Dummy model SQS queue
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "workflow_dummy_queue" {
  name = join("-", ["mdl", "dummy", "queue"])

  message_retention_seconds  = 3600
  visibility_timeout_seconds = 30

  tags = var.project_tags
}


# ---------------------------------------------------------------------------
# Shared environment variables for Lambdas that load the queue map from S3.
#
# The QUEUE_MAP in Python is built at runtime by loading models_config.json
# from S3 (same source as the polling Lambda). This avoids one env var per
# model and stays consistent as the model catalogue grows.
# ---------------------------------------------------------------------------

locals {
  workflow_env = {
    WORKFLOW_TEMPLATE_TABLE  = aws_dynamodb_table.workflow_templates.id
    WORKFLOW_STATE_TABLE     = aws_dynamodb_table.workflow_state.id
    WORKFLOW_STEPS_TABLE     = aws_dynamodb_table.workflow_steps.id
    WORKFLOW_TASKS_TABLE     = aws_dynamodb_table.workflow_tasks.id
    QUEUE_URL_DUMMY          = aws_sqs_queue.workflow_dummy_queue.url
    AWS_S3_ASSETS_BUCKET_NAME = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT  = aws_s3_object.models_config_internal.key
  }
}


# ---------------------------------------------------------------------------
# workflow_api Lambda
# ---------------------------------------------------------------------------

module "workflow_api_lambda" {
  source  = "terraform-aws-modules/lambda/aws"

  function_name = join("-", [var.org_name, var.project_name, var.env, "workflow-api"])
  description   = "workflow template management and execution status API"
  hash_extra    = "workflow api"

  cloudwatch_logs_retention_in_days = 5

  runtime     = var.lambda_runtime
  source_path = [{
    path = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.workflow.txt"])
  }]
  handler     = "tools.workflow.api_handler.handler"

  environment_variables = local.workflow_env

  policy_statements = {
    template_table = {
      effect  = "Allow"
      actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
      resources = [aws_dynamodb_table.workflow_templates.arn]
    }

    state_table = {
      effect  = "Allow"
      actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"]
      resources = [aws_dynamodb_table.workflow_state.arn]
    }

    steps_table_read = {
      effect  = "Allow"
      actions = ["dynamodb:GetItem", "dynamodb:Query"]
      resources = [aws_dynamodb_table.workflow_steps.arn]
    }

    tasks_table = {
      effect  = "Allow"
      actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"]
      resources = [aws_dynamodb_table.workflow_tasks.arn]
    }

    sqs_dispatch = {
      effect  = "Allow"
      actions = ["sqs:SendMessage"]
      resources = concat(
        [for q in aws_sqs_queue.model_queues : q.arn],
        [aws_sqs_queue.workflow_dummy_queue.arn],
      )
    }

    s3_read_models_config = {
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [aws_s3_object.models_config_internal.arn]
    }

    apigateway_get_key = {
      effect    = "Allow"
      actions   = ["apigateway:GET"]
      resources = ["arn:aws:apigateway:${var.region}::/apikeys/*"]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}


# ---------------------------------------------------------------------------
# workflow_executor Lambda
# ---------------------------------------------------------------------------

module "workflow_executor_lambda" {
  source  = "terraform-aws-modules/lambda/aws"

  function_name = join("-", [var.org_name, var.project_name, var.env, "workflow-executor"])
  description   = "advances runfox workflow state on step result"
  hash_extra    = "workflow executor"

  cloudwatch_logs_retention_in_days = 5

  runtime     = var.lambda_runtime
  source_path = [{
    path = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.workflow.txt"])
  }]
  handler     = "tools.workflow.executor.handler"

  environment_variables = local.workflow_env

  policy_statements = {
    state_table = {
      effect  = "Allow"
      actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
      resources = [aws_dynamodb_table.workflow_state.arn]
    }

    tasks_table = {
      effect  = "Allow"
      actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"]
      resources = [aws_dynamodb_table.workflow_tasks.arn]
    }

    sqs_dispatch = {
      effect  = "Allow"
      actions = ["sqs:SendMessage"]
      resources = concat(
        [for q in aws_sqs_queue.model_queues : q.arn],
        [aws_sqs_queue.workflow_dummy_queue.arn],
      )
    }

    s3_read_models_config = {
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [aws_s3_object.models_config_internal.arn]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}


# ---------------------------------------------------------------------------
# workflow_stream_handler Lambda
# ---------------------------------------------------------------------------

module "workflow_stream_handler_lambda" {
  source  = "terraform-aws-modules/lambda/aws"

  function_name = join("-", [var.org_name, var.project_name, var.env, "workflow-stream-handler"])
  description   = "routes workflow step completions from DynamoDB Streams to executor"
  hash_extra    = "workflow stream handler"

  cloudwatch_logs_retention_in_days = 5

  runtime     = var.lambda_runtime
  source_path = [{
    path = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.workflow.txt"])
  }]
  handler     = "tools.workflow.dynamodb_stream_handler.handler"

  environment_variables = {
    WORKFLOW_EXECUTOR_FUNCTION = module.workflow_executor_lambda.lambda_function_name
  }

  policy_statements = {
    dynamodb_streams = {
      effect = "Allow"
      actions = [
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:DescribeStream",
        "dynamodb:ListStreams",
      ]
      resources = [aws_dynamodb_table.workflow_steps.stream_arn]
    }

    invoke_executor = {
      effect    = "Allow"
      actions   = ["lambda:InvokeFunction"]
      resources = [module.workflow_executor_lambda.lambda_function_arn]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_event_source_mapping" "workflow_steps_stream" {
  event_source_arn  = aws_dynamodb_table.workflow_steps.stream_arn
  function_name     = module.workflow_stream_handler_lambda.lambda_function_arn
  starting_position = "LATEST"
  batch_size        = 10

  filter_criteria {
    filter {
      pattern = jsonencode({
        dynamodb = {
          NewImage = {
            status = { S = ["complete"] }
          }
        }
      })
    }
  }
}


# ---------------------------------------------------------------------------
# workflow_dummy_model Lambda
# ---------------------------------------------------------------------------

module "workflow_dummy_model_lambda" {
  source  = "terraform-aws-modules/lambda/aws"

  function_name = join("-", [var.org_name, var.project_name, var.env, "workflow-dummy-model"])
  description   = "dummy model worker for workflow end-to-end testing"
  hash_extra    = "workflow dummy model"

  cloudwatch_logs_retention_in_days = 5

  runtime     = var.lambda_runtime
  source_path = [{
    path = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.workflow.txt"])
  }]
  handler     = "tools.workflow.model_dummy.handler"

  environment_variables = {
    WORKFLOW_STEPS_TABLE = aws_dynamodb_table.workflow_steps.id
  }

  policy_statements = {
    sqs_receive = {
      effect  = "Allow"
      actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = [aws_sqs_queue.workflow_dummy_queue.arn]
    }

    steps_table = {
      effect  = "Allow"
      actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
      resources = [aws_dynamodb_table.workflow_steps.arn]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_event_source_mapping" "workflow_dummy_queue" {
  event_source_arn = aws_sqs_queue.workflow_dummy_queue.arn
  function_name    = module.workflow_dummy_model_lambda.lambda_function_arn
  batch_size       = 1
}


# ---------------------------------------------------------------------------
# ECS task role: workflow_steps write access for real model workers
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "model_task_workflow_steps" {
  name   = join("-", [var.project_name, var.env, "ecs-task-workflow-steps"])
  role   = aws_iam_role.model_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WorkflowStepsWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.workflow_steps.arn
      }
    ]
  })
}


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "workflow_api_lambda" {
  value = module.workflow_api_lambda.lambda_function_name
}

output "workflow_executor_lambda" {
  value = module.workflow_executor_lambda.lambda_function_name
}

output "workflow_stream_handler_lambda" {
  value = module.workflow_stream_handler_lambda.lambda_function_name
}

output "workflow_dummy_model_lambda" {
  value = module.workflow_dummy_model_lambda.lambda_function_name
}

output "workflow_api_lambda_arn" {
  value = module.workflow_api_lambda.lambda_function_arn
}

output "workflow_executor_lambda_arn" {
  value = module.workflow_executor_lambda.lambda_function_arn
}

output "workflow_templates_table" {
  value = aws_dynamodb_table.workflow_templates.id
}

output "workflow_state_table" {
  value = aws_dynamodb_table.workflow_state.id
}

output "workflow_steps_table" {
  value = aws_dynamodb_table.workflow_steps.id
}

output "workflow_dummy_queue_url" {
  value = aws_sqs_queue.workflow_dummy_queue.url
}
