#
# lambdas for long running job submission
#
resource "aws_dynamodb_table" "results_cache" {
  name         = join("-", [var.org_name, var.project_name, var.env, "results-cache"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK" # userid
    type = "S"
  }

  attribute {
    name = "SK" # messageid
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.project_tags
}

module "instruct_polling" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 3.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "instruct-polling"])
  description   = "polling lambda"

  cloudwatch_logs_retention_in_days = 5

  runtime     = "python3.11"
  source_path = join("/", [path.module, "..", "..", "package", "src", "tools", "polling", "main.py"])
  handler     = "main.handler"

  environment_variables = {
    INPUT_PATH     = "/instruct"
    POLL_PATH      = "/instruct/{message_id}"
    SFN_ARN        = module.instruct.state_machine_arn
    DYNAMODB_TABLE = aws_dynamodb_table.results_cache.arn
  }

  policy_statements = {

    trigger_sfn = {
      effect = "Allow"
      actions = [
        "states:StartExecution"
      ]
      resources = [module.instruct.state_machine_arn]
    }

    db_access = {
      effect = "Allow",
      actions = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem"
      ],
      resources = [aws_dynamodb_table.results_cache.arn]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}

module "embed_polling" {
  # FIXME: pass the target sfn arn at runtime and use a single polling lambda
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 3.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "embed-polling"])
  description   = "embed lambda"

  cloudwatch_logs_retention_in_days = 5

  runtime     = "python3.11"
  source_path = join("/", [path.module, "..", "..", "package", "src", "tools", "polling", "main.py"])
  handler     = "main.handler"

  environment_variables = {
    INPUT_PATH     = "/embed/text"
    POLL_PATH      = "/embed/text/{message_id}"
    SFN_ARN        = module.text_embedding.state_machine_arn
    DYNAMODB_TABLE = aws_dynamodb_table.results_cache.arn
  }

  policy_statements = {

    trigger_sfn = {
      effect = "Allow"
      actions = [
        "states:StartExecution"
      ]
      resources = [module.text_embedding.state_machine_arn]
    }

    db_access = {
      effect = "Allow",
      actions = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem"
      ],
      resources = [aws_dynamodb_table.results_cache.arn]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}
