#
# API Gateway usage plan and native key support
#
resource "aws_api_gateway_usage_plan" "default" {
  name = join("-", [var.org_name, var.project_name, var.env, "usage-plan"])

  api_stages {
    api_id = aws_api_gateway_rest_api.default.id
    stage  = aws_api_gateway_stage.default.stage_name
  }
}

#
# master key for the project owner, created once in terraform
# retrieve the value with:
#   terraform -chdir=tf/03 output -raw master_api_key_value
#
resource "aws_api_gateway_api_key" "master" {
  name = "${var.master_key_email}/master"
}

resource "aws_api_gateway_usage_plan_key" "master" {
  key_id        = aws_api_gateway_api_key.master.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.default.id
}

output "master_api_key_value" {
  value     = aws_api_gateway_api_key.master.value
  sensitive = true
}

#
# api key management lambda
#
module "apikey_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "apikey"])
  description   = "api key management"
  hash_extra    = "apikey"

  cloudwatch_logs_retention_in_days = 5

  handler = "main.lambda_handler"
  runtime = var.lambda_runtime

  source_path = [
    {
      path             = join("/", [path.module, "lambdas", "apikey", "main.py"])
      pip_requirements = join("/", [path.module, "lambdas", "apikey", "requirements.txt"])
    }
  ]

  environment_variables = {
    APPEND_CORS_HEADERS = "True"
    LOG_LEVEL           = "INFO"
    USAGE_PLAN_NAME     = join("-", [var.org_name, var.project_name, var.env, "usage-plan"])
  }

  policy_statements = {
    apigateway_key_read = {
      effect  = "Allow"
      actions = ["apigateway:GET"]
      resources = [
        "arn:aws:apigateway:${var.region}::/apikeys",
        "arn:aws:apigateway:${var.region}::/apikeys/*",
      ]
    }

    apigateway_key_write = {
      effect  = "Allow"
      actions = ["apigateway:POST", "apigateway:DELETE"]
      resources = [
        "arn:aws:apigateway:${var.region}::/apikeys",
        "arn:aws:apigateway:${var.region}::/apikeys/*",
      ]
    }

    apigateway_usage_plan_key_write = {
      effect  = "Allow"
      actions = ["apigateway:POST", "apigateway:DELETE"]
      resources = [
        "arn:aws:apigateway:${var.region}::/usageplans/*/keys",
        "arn:aws:apigateway:${var.region}::/usageplans/*/keys/*",
      ]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}

#
# allow api gateway to invoke the key management lambda
#
resource "aws_iam_role_policy" "apigateway_apikey_lambda" {
  name = join("-", [var.org_name, var.project_name, var.env, "apigw-apikey-invoke"])
  role = aws_iam_role.apigateway_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = module.apikey_lambda.lambda_function_arn
      }
    ]
  })
}
