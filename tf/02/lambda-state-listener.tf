module "state_listener_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "state-listener"])
  description                       = "Receives lifecycle events, writes request state to DynamoDB"
  hash_extra                        = "state-listener"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime

  reserved_concurrent_executions = 1

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.state_listener.handler"

  environment_variables = {
    RESULTS_TABLE = aws_dynamodb_table.results_cache.id
    WORKER_EVENTS_TABLE = aws_dynamodb_table.events.id
    INSTANCE_EVENTS_TABLE = aws_dynamodb_table.events.id
    BUILD_VERSION  = var.git_tag
  }

  policy_statements = {
    db_write = {
      effect  = "Allow"
      actions = [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
      ]
      resources = [
        aws_dynamodb_table.results_cache.arn,
        aws_dynamodb_table.events.arn,
      ]
    }

    db_read = {
      effect  = "Allow"
      actions = [
        "dynamodb:GetItem"
      ]
      resources = [
        aws_dynamodb_table.results_cache.arn,
        aws_dynamodb_table.events.arn,
      ]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

resource "aws_lambda_permission" "sns_invoke_state_listener" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.state_listener_lambda.lambda_function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.lifecycle.arn
}

resource "aws_sns_topic_subscription" "state_listener" {
  topic_arn = aws_sns_topic.lifecycle.arn
  protocol  = "lambda"
  endpoint  = module.state_listener_lambda.lambda_function_arn

  # No filter -- state_listener handles all event types
  # that have a state transition defined in STATE_MAP
}
