locals {
  rest_api_public_definition = "${path.module}/rest/api_public_definition.json"
  api_public_definition_hash = local.rest_api_public_definition

  rest_api_private_definition = "${path.module}/rest/api_private_definition.json"
  api_private_definition_hash = local.rest_api_private_definition
}

resource "aws_cloudwatch_log_group" "embed" {
  name              = join("/", ["api-gateway", var.project_name, var.env])
  retention_in_days = 7
}

resource "aws_iam_role" "apigateway_stepfunctions" {
  name = "APIGatewayStepFunctionsRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "apigateway_stepfunctions_policy" {
  role = aws_iam_role.apigateway_stepfunctions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "states:StartSyncExecution"
        Effect   = "Allow"
        Resource = [
          data.aws_sfn_state_machine.text_embedding.arn,
          data.aws_sfn_state_machine.instruct.arn,
          data.aws_sfn_state_machine.tts.arn,
        ]
      }
    ]
  })
}

resource "aws_iam_role" "apigateway_lambda" {
  name = join("-", [var.org_name, var.project_name, var.env, "apigw-lambda-invoke"])

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "apigateway_lambda_policy" {
  role = aws_iam_role.apigateway_lambda.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "lambda:InvokeFunction",
        Effect = "Allow",
        Resource = [
          data.aws_lambda_function.instruct_polling.arn,
          data.aws_lambda_function.embed_polling.arn,
        ]
      }
    ]
  })
}


#resource "aws_iam_role" "apigateway_s3_read" {
#  name = join("-", [var.org_name, var.project_name, var.env, "apigw-s3-read"])
#
#  assume_role_policy = jsonencode({
#    Version = "2012-10-17",
#    Statement = [
#      {
#        Action = "sts:AssumeRole",
#        Effect = "Allow",
#        Principal = {
#          Service = "apigateway.amazonaws.com"
#        }
#      }
#    ]
#  })
#}
#
#resource "aws_iam_role_policy" "apigateway_s3_read_policy" {
#  role = aws_iam_role.apigateway_s3_read.id
#
#  policy = jsonencode({
#    Version = "2012-10-17",
#    Statement = [
#      {
#        Effect = "Allow",
#        Action = "s3:GetObject",
#        Resource = [ "${aws_s3_bucket.www.arn}/docs/models.json"
#        ]
#      }
#    ]
#  })
#}

resource "aws_api_gateway_rest_api" "embed" {
  name        = join("-", [var.org_name, var.project_name, var.env, "api"])

  body = templatefile(local.rest_api_private_definition, {
    project_name = var.project_name
    project_host = local.api_domain

#    text_embedding_step_function_arn = data.aws_sfn_state_machine.text_embedding.arn
#    text_embedding_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn
    #polling_start_step_function_arn = data.aws_sfn_state_machine.polling_start.arn
    polling_start_lambda_arn = data.aws_lambda_function.embed_polling.invoke_arn
    polling_start_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn
    text_embedding_step_function_arn = data.aws_sfn_state_machine.text_embedding.arn
    text_embedding_step_function_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    image_embedding_step_function_arn = data.aws_sfn_state_machine.text_embedding.arn
    image_embedding_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

    instruct_step_function_arn = data.aws_sfn_state_machine.instruct.arn
    instruct_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

    instruct_polling_arn = data.aws_lambda_function.instruct_polling.invoke_arn
    instruct_polling_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn # TODO: lambda invoke role

    tts_step_function_arn = data.aws_sfn_state_machine.tts.arn
    tts_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

#    models_definition_arn = "arn:aws:apigateway:${var.region}:s3:path/${aws_s3_bucket.www.id}/docs/models.json"
#    models_definition_iam_role_arn = aws_iam_role.apigateway_s3_read.arn

    region = var.region
  })
}

resource "aws_api_gateway_deployment" "embed" {
  depends_on = [
    # aws_api_gateway_integration.example
  ]

  triggers = {
    redeployment = local.api_private_definition_hash
  }

  rest_api_id = aws_api_gateway_rest_api.embed.id

  # Use a description or a unique identifier to trigger a new deployment on updates
  description = "${timestamp()} hash ${local.api_private_definition_hash}"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "embed" {
  stage_name    = "v1"
  rest_api_id   = aws_api_gateway_rest_api.embed.id
  deployment_id = aws_api_gateway_deployment.embed.id

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.embed.arn
    format           = "$context.identity.sourceIp - - [$context.requestTime] \"$context.httpMethod $context.routeKey $context.protocol\" $context.status $context.responseLength $context.requestId $context.integrationErrorMessage $context.error.message $context.error.messageString $context.error.responseType"
  }
}

resource "aws_iam_role" "api_gw_cloudwatch_log_role" {
  name = join("-", [var.project_name, var.env, "api_gw_cloudwatch_log_role"])

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "apigateway.amazonaws.com"
        },
      },
    ],
  })
}

resource "aws_iam_role_policy_attachment" "api_gw_cloudwatch_log_policy_attach" {
  role       = aws_iam_role.api_gw_cloudwatch_log_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_base_path_mapping" "domain" {
  api_id      = aws_api_gateway_rest_api.embed.id
  stage_name  = aws_api_gateway_deployment.embed.stage_name
  domain_name = aws_api_gateway_domain_name.domain.domain_name
}

#
# api key for testing
#
resource "aws_api_gateway_usage_plan" "test" {
  name        = join("-", [var.project_name, var.env, "usage-plan"])
  description = "Example Usage Plan created by Terraform"

  api_stages {
    api_id = aws_api_gateway_stage.embed.rest_api_id
    stage  = aws_api_gateway_stage.embed.stage_name
  }

  quota_settings {
    limit  = 50000
    offset = 2
    period = "WEEK"
  }

  throttle_settings {
    burst_limit = 200
    rate_limit  = 100
  }
}

resource "aws_api_gateway_api_key" "test" {
  name        = join("-", [var.project_name, var.env, "test-api-key"])
  description = "Example API Key created by Terraform"
  enabled     = true
}

resource "aws_api_gateway_usage_plan_key" "test" {
  key_id        = aws_api_gateway_api_key.test.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.test.id
}

output "api_key_value" {
  value = aws_api_gateway_api_key.test.value
  sensitive = true
}
