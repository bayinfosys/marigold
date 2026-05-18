module "request_receiver_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "request-receiver"])
  description                       = "Validates requests, writes to SQS, publishes lifecycle event to SNS"
  hash_extra                        = "request-receiver"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.request_receiver.handler"

  environment_variables = {
    DYNAMODB_TABLE            = aws_dynamodb_table.results_cache.id
    APPEND_CORS_HEADERS       = "True"
    AWS_S3_ASSETS_BUCKET_NAME = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT   = aws_s3_object.models_config_internal.key
    CACHE_STATE_S3_OBJECT     = "cache_state.json"
    LIFECYCLE_TOPIC_ARN       = aws_sns_topic.lifecycle.arn
    ANONCHAT_QUEUE_URL        = aws_sqs_queue.anonchat_queue.url
    ANONCHAT_MODEL            = var.anonchat_model
    BUILD_VERSION             = var.git_tag
  }

  policy_statements = {
    db_access = {
      effect  = "Allow"
      actions = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
      ]
      resources = [aws_dynamodb_table.results_cache.arn]
    }

    s3_list = {
      effect    = "Allow"
      actions   = ["s3:ListBucket"]
      resources = [aws_s3_bucket.data.arn]
    }

    s3_read = {
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        aws_s3_object.models_config_internal.arn,
        aws_s3_object.models_json.arn,
        "${aws_s3_bucket.data.arn}/cache_state.json",
      ]
    }

    sqs_send = {
      effect  = "Allow"
      actions = ["sqs:SendMessage"]
      resources = concat(
        [for x in aws_sqs_queue.model_queues : x.arn],
        [aws_sqs_queue.anonchat_queue.arn],
      )
    }

    sns_publish = {
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.lifecycle.arn]
    }

    apigateway_read = {
      effect  = "Allow"
      actions = ["apigateway:GET"]
      resources = [
        "arn:aws:apigateway:${var.region}::/apikeys/*"
      ]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}

output "request_receiver_lambda" {
  value = module.request_receiver_lambda.lambda_function_name
}
