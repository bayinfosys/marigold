module "usage_table" {
  source = "terraform-aws-modules/dynamodb-table/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "usage"])

  hash_key  = "PK"
  range_key = "SK"

  attributes = [
    {
      name = "PK"
      type = "S"
    },
    {
      name = "SK"
      type = "S"
    }
  ]

  stream_enabled = true
  stream_view_type = "NEW_IMAGE"

  tags = var.project_tags
}


module "usage_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-logger"])
  description   = "account usage stats"

  cloudwatch_logs_retention_in_days = 5

  handler     = "main.sqs_handler"
  runtime     = "python3.11"
  source_path = [
    {
      path = join("/", [path.module, "lambdas", "usage", "main.py"]),
      pip_requirements = join("/", [path.module, "lambdas", "usage", "requirements.txt"]),
    }
  ]

  environment_variables = {
    DYNAMODB_USAGE_TABLE = module.usage_table.dynamodb_table_id
    APPEND_CORS_HEADERS = "True"
    LOG_LEVEL = "INFO"
  }

  attach_policy_statements = true

  policy_statements = {
    dynamodb_access = {
      effect = "Allow"
      actions = [
        "dynamodb:PutItem",
      ]
      resources = [
        module.usage_table.dynamodb_table_arn
      ]
    }

    dynamodb_list_tables = {
      effect = "Allow"
      actions = [
        "dynamodb:ListTables",
        "dynamodb:CreateTable"
      ]
      resources = [
        "*"
      ]
    }

    sqs_read = {
      effect    = "Allow",
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      resources = [aws_sqs_queue.usage.arn]
    }
  }

  tags = var.project_tags
}

resource "aws_sqs_queue" "usage" {
  name                      = join("-", [var.org_name, var.project_name, var.env, "usage-queue"])
  delay_seconds             = 90
  max_message_size          = 2048
  message_retention_seconds = 86400
  receive_wait_time_seconds = 10

  tags = var.project_tags
}

resource "aws_lambda_event_source_mapping" "usage" {
  event_source_arn  = aws_sqs_queue.usage.arn
  function_name     = module.usage_lambda.lambda_function_arn

  tags = var.project_tags
}


module "usage_stats_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "usage", "logger-stats"])
  description   = "account usage stats summaries"

  cloudwatch_logs_retention_in_days = 5

  handler     = "main.dynamodb_stream_handler"
  runtime     = "python3.11"
  source_path = [
    {
      path = join("/", [path.module, "lambdas", "usage-stats", "main.py"]),
      pip_requirements = join("/", [path.module, "lambdas", "usage-stats", "requirements.txt"]),
    }
  ]

  environment_variables = {
    DYNAMODB_USAGE_TABLE = module.usage_table.dynamodb_table_id
    LOG_LEVEL = "INFO"
  }

  attach_policy_statements = true

  policy_statements = {
    dynamodb_access = {
      effect = "Allow"
      actions = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
      ]
      resources = [
        module.usage_table.dynamodb_table_arn,
      ]
    }

    dynamodb_stream_access = {
      effect = "Allow"
      actions = [
        "dynamodb:GetRecords",
        "dynamodb:DescribeStream",
        "dynamodb:ListStreams",
        "dynamodb:GetShardIterator"
      ]
      resources = [
        module.usage_table.dynamodb_table_stream_arn,
      ]
    }
  }

  tags = var.project_tags
}

resource "aws_lambda_event_source_mapping" "usage_stats" {
  event_source_arn  = module.usage_table.dynamodb_table_stream_arn
  function_name     = module.usage_stats_lambda.lambda_function_arn

  starting_position = "LATEST"

  tags = var.project_tags
}

module "api_usage_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-fetch"])
  description   = "api access to usage stats summaries"

  cloudwatch_logs_retention_in_days = 5

  handler     = "tools.usage.main.handler"
  runtime     = "python3.11"
  source_path = [
    {
      path = join("/", [path.module, "..", "..", "package", "src"]),
      pip_requirements = join("/", [path.module, "lambdas", "usage-stats", "requirements.txt"]),
    }
  ]

  environment_variables = {
    DYNAMODB_USAGE_TABLE = module.usage_table.dynamodb_table_id
    APPEND_CORS_HEADERS = "True"
    LOG_LEVEL = "INFO"
  }

  attach_policy_statements = true

  policy_statements = {
    dynamodb_access = {
      effect = "Allow"
      actions = [
        "dynamodb:GetItem",
        "dynamodb:Query",
      ]
      resources = [
        module.usage_table.dynamodb_table_arn,
      ]
    }
  }

  tags = var.project_tags
}
