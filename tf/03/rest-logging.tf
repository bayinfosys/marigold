# ---------------------------------------------------------------------------
# API Gateway access logging, usage event capture, and API key usage fetch.
#
# Flow:
#   API Gateway stage
#     -> CloudWatch log group (access logs, JSON format)
#     -> subscription filter
#     -> api_logger_lambda  (writes raw events to usage table in layer 02)
#
# api_usage_lambda serves the raw events to the API for billing visibility.
# ---------------------------------------------------------------------------

locals {
  access_log_format = jsonencode({
    requestId            = "$context.requestId"
    stage                = "$context.stage"
    epochMs              = "$context.requestTimeEpoch"
    requestTime          = "$context.requestTime"
    method               = "$context.httpMethod"
    resourcePath         = "$context.resourcePath"
    status               = "$context.status"
    responseBytes        = "$context.responseLength"
    responseLatencyMs    = "$context.responseLatency"
    integrationLatencyMs = "$context.integration.latency"
    sourceIp             = "$context.identity.sourceIp"
    userAgent            = "$context.identity.userAgent"
    apiKeyId             = "$context.identity.apiKeyId"
    errorMessage         = "$context.error.message"
    errorType            = "$context.error.responseType"
    integrationError     = "$context.integration.error"
  })
}

# ---------------------------------------------------------------------------
# api-logger: receives CloudWatch subscription events, writes raw usage rows
# ---------------------------------------------------------------------------

module "api_logger_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "api-logger"])
  description   = "parse API Gateway access logs and write raw usage events"
  hash_extra    = "api-logger"

  cloudwatch_logs_retention_in_days = 5

  handler     = "main.handler"
  runtime     = var.lambda_runtime
  source_path = [
    {
      path             = join("/", [path.module, "lambdas", "api-logger", "main.py"])
      pip_requirements = join("/", [path.module, "lambdas", "api-logger", "requirements.txt"])
    }
  ]

  environment_variables = {
    DYNAMODB_USAGE_TABLE = data.terraform_remote_state.pipelines.outputs["usage_table_id"]
    LOG_LEVEL            = "INFO"
  }

  attach_policy_statements = true

  policy_statements = {
    dynamodb_write = {
      effect    = "Allow"
      actions   = ["dynamodb:PutItem"]
      resources = [data.terraform_remote_state.pipelines.outputs["usage_table_arn"]]
    }
  }

  tags = var.project_tags
}

resource "aws_lambda_permission" "cloudwatch_logs_invoke" {
  statement_id   = "AllowCloudWatchLogsInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = module.api_logger_lambda.lambda_function_name
  principal      = "logs.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Subscription filter -- forwards all access log events to api_logger_lambda.
# Unauthenticated requests are filtered out inside the lambda.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_subscription_filter" "api_access_logs" {
  name            = join("-", [var.org_name, var.project_name, var.env, "api-access-logs"])
  log_group_name  = aws_cloudwatch_log_group.default.name
  filter_pattern  = ""
  destination_arn = module.api_logger_lambda.lambda_function_arn

  depends_on = [aws_lambda_permission.cloudwatch_logs_invoke]
}

# ---------------------------------------------------------------------------
# api_usage_lambda: serves raw usage events to the API
# ---------------------------------------------------------------------------

module "api_usage_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-fetch"])
  description   = "serve raw usage events to the API"
  hash_extra    = "usage-fetch"

  cloudwatch_logs_retention_in_days = 5

  handler     = "tools.usage.main.handler"
  runtime     = var.lambda_runtime
  source_path = [
    {
      path             = join("/", [path.module, "..", "..", "package", "src"])
      pip_requirements = join("/", [path.module, "lambdas", "api-logger", "requirements.txt"])
    }
  ]

  environment_variables = {
    DYNAMODB_USAGE_TABLE = data.terraform_remote_state.pipelines.outputs["usage_table_id"]
    APPEND_CORS_HEADERS  = "True"
    LOG_LEVEL            = "INFO"
  }

  attach_policy_statements = true

  policy_statements = {
    dynamodb_read = {
      effect    = "Allow"
      actions   = ["dynamodb:GetItem", "dynamodb:Query"]
      resources = [data.terraform_remote_state.pipelines.outputs["usage_table_arn"]]
    }
  }

  tags = var.project_tags
}
