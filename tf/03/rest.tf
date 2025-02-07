locals {
  rest_api_public_definition = "${path.module}/rest/api_public_definition.json"
  api_public_definition_hash = local.rest_api_public_definition

  rest_api_private_definition = "${path.module}/rest/api_private_definition.json"
  api_private_definition_hash = local.rest_api_private_definition
}

resource "aws_cloudwatch_log_group" "default" {
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
          data.aws_lambda_function.tts_polling.arn,
          data.aws_lambda_function.usage_stats.arn,
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

resource "aws_api_gateway_rest_api" "default" {
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

    instruct_polling_start_lambda_arn = data.aws_lambda_function.instruct_polling.invoke_arn
    instruct_polling_start_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    instruct_polling_check_lambda_arn = data.aws_lambda_function.instruct_polling.invoke_arn
    instruct_polling_check_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn


    tts_polling_start_lambda_arn = data.aws_lambda_function.tts_polling.invoke_arn
    tts_polling_start_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    tts_polling_check_lambda_arn = data.aws_lambda_function.tts_polling.invoke_arn
    tts_polling_check_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn


    image_embedding_step_function_arn = data.aws_sfn_state_machine.text_embedding.arn
    image_embedding_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

#    instruct_step_function_arn = data.aws_sfn_state_machine.instruct.arn
#    instruct_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

#    tts_step_function_arn = data.aws_sfn_state_machine.tts.arn
#    tts_step_function_iam_role_arn = aws_iam_role.apigateway_stepfunctions.arn

#    models_definition_arn = "arn:aws:apigateway:${var.region}:s3:path/${aws_s3_bucket.www.id}/docs/models.json"
#    models_definition_iam_role_arn = aws_iam_role.apigateway_s3_read.arn

    lambda_authorizer_name = join("-", [var.org_name, "vecdb", var.env, "auth"])
    lambda_authorizer_uri = data.aws_lambda_function.authorizer_lambda.invoke_arn
    lambda_authorizer_iam_role_arn = aws_iam_role.invocation_role.arn

    # usage
    usage_stats_lambda_arn = data.aws_lambda_function.usage_stats.invoke_arn
    usage_stats_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    region = var.region
  })
}

resource "aws_api_gateway_deployment" "default" {
  triggers = {
    redeployment = sha1(jsonencode(aws_api_gateway_rest_api.default.body))
  }

  rest_api_id = aws_api_gateway_rest_api.default.id

  # Use a description or a unique identifier to trigger a new deployment on updates
  description = "${timestamp()} hash ${local.api_private_definition_hash}"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "default" {
  stage_name    = "v1"
  rest_api_id   = aws_api_gateway_rest_api.default.id
  deployment_id = aws_api_gateway_deployment.default.id

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.default.arn
    format           = "$context.identity.sourceIp - - [$context.requestTime] \"$context.httpMethod $context.resourcePath $context.protocol\" $context.status $context.responseLength $context.requestId $context.integration.integrationStatus $context.integrationErrorMessage $context.error.message $context.error.messageString $context.integration.error"
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
  api_id      = aws_api_gateway_rest_api.default.id
  stage_name  = aws_api_gateway_deployment.default.stage_name
  domain_name = aws_api_gateway_domain_name.domain.domain_name
}

#
# authorizer from the other project
# NB: we need a local iam rule to invoke the authorizer from this apigw
#
resource "aws_iam_role" "invocation_role" {
  name = join("-", [var.org_name, var.project_name, var.env, "invocation-role"])

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_invoke" {
  role       = aws_iam_role.invocation_role.name
  policy_arn = aws_iam_policy.lambda_invoke_policy.arn
}

resource "aws_iam_policy" "lambda_invoke_policy" {
  name        = join("-", [var.org_name, var.project_name, var.env, "lambda-invoke-policy"])
  description = "Policy to allow API Gateway to invoke the Lambda authorizer."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource =  data.aws_lambda_function.authorizer_lambda.arn
      },
    ]
  })
}
