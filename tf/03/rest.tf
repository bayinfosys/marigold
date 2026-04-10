locals {
  rest_api_public_definition = "${path.module}/rest/api_public_definition.json"
  api_public_definition_hash = filesha256(local.rest_api_public_definition)

  rest_api_private_definition = "${path.module}/rest/api_private_definition.json"
  api_private_definition_hash = filesha256(local.rest_api_private_definition)
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
          data.aws_lambda_function.polling_start_lambda_arn.arn,
          # data.aws_lambda_function.usage_stats.arn,
          data.aws_lambda_function.workflow_api_lambda.arn,
        ]
      },
      {
        Action = "s3:GetObject",
        Effect = "Allow",
        Resource = [
          "${data.aws_s3_bucket.results.arn}/*",
          "${data.aws_s3_bucket.assets.arn}/*",
          "${data.aws_s3_bucket.model_outputs.arn}/outputs/*",
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

    # auth
    apikey_authorizer_name = "apikey_auth"  # FIXME
    # cognito_authorizer_name = "cognito_auth"  # FIXME
    # cognito_user_pool_arn = "cognito_user_pool_arn"  # FIXME

    polling_start_lambda_arn = data.aws_lambda_function.polling_start_lambda_arn.invoke_arn
    polling_start_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    # usage
    #usage_stats_lambda_arn = "xxx" # data.aws_lambda_function.usage_stats.invoke_arn
    #usage_stats_lambda_iam_role_arn = "xxx"  # aws_iam_role.apigateway_lambda.arn

    # binary model outputs
    s3_output_bucket_name       = data.aws_s3_bucket.model_outputs.id
    s3_read_output_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    # web assets
    s3_assets_bucket_name           = data.aws_s3_bucket.assets.id
    s3_read_api_object_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    # apikey
    key_management_lambda_arn         = module.apikey_lambda.lambda_function_invoke_arn
    key_management_lambda_iam_role_arn = aws_iam_role.apigateway_lambda.arn

    # workflows
    workflow_api_lambda_arn          = data.aws_lambda_function.workflow_api_lambda.invoke_arn
    workflow_api_lambda_iam_role_arn  = aws_iam_role.apigateway_lambda.arn

    region = var.region
  })
}

resource "aws_api_gateway_deployment" "default" {
  triggers = {
    redeployment = sha1(jsonencode(aws_api_gateway_rest_api.default.body))
  }

  rest_api_id = aws_api_gateway_rest_api.default.id

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
    format          = local.access_log_format
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
  stage_name  = aws_api_gateway_stage.default.stage_name
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

#
# openapi.json public file
#
resource "aws_s3_object" "api_export_object" {
  bucket = data.aws_s3_bucket.assets.id
  key    = "openapi.json"

  content_type = "application/json"
  content = file(local.rest_api_public_definition)
}
