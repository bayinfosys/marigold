#
# lambdas for long running job submission
# NB: all the polling functions are the same, just with slightly different parameters
#     so we should merge them into a single lambda, if possible. This will require
#     parameters to be passed from the apigw and step functions on lambda invocation.
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

resource "aws_s3_bucket" "results_bucket" {
  bucket_prefix = join("-", [var.org_name, var.project_name, var.env, "results-cache"])

  tags = var.project_tags
}

resource "aws_s3_bucket_lifecycle_configuration" "results_cache" {
  bucket = aws_s3_bucket.results_bucket.id

  rule {
    id     = "Move to STANDARD_IA after 10 days"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

output "results_bucket" {
  value = aws_s3_bucket.results_bucket.id
}

resource "aws_s3_object" "models_config_internal" {
  bucket       = aws_s3_bucket.data.id
  key          = "models_config.json"
  content_type = "application/json"

  content = jsonencode({
    for name, conf in var.models : md5(conf.environment_variables["MODELNAME"]) => {
      queue_url            = aws_sqs_queue.model_queues[name].url
      model_name           = conf.environment_variables["MODELNAME"]
      task_definition      = aws_ecs_task_definition.model_tasks[name].arn
      family               = aws_ecs_task_definition.model_tasks[name].family
      model_type           = conf.environment_variables["MODEL_TYPE"]
    }
  })
}

module "polling_lambda" {
  source  = "terraform-aws-modules/lambda/aws"

  function_name = join("-", [var.org_name, var.project_name, var.env, "polling", "ecs"])
  description   = "instruct polling (ecs)"
  hash_extra    = "instruct polling ecs"

  cloudwatch_logs_retention_in_days = 5

  runtime     = var.lambda_runtime
  source_path = [{
    path = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]
  handler     = "tools.polling.ecs.handler"

  environment_variables = {
    ECS_CLUSTER_ARN = module.ecs.cluster_arn
    ECS_SUBNETS = join(",", [for x in data.aws_subnet.private_subnets: x.id])
    ECS_SECURITY_GROUPS = join(",", [data.aws_security_group.lambda_sg.id])
    DYNAMODB_TABLE = aws_dynamodb_table.results_cache.id
    APPEND_CORS_HEADERS = "True"
    AWS_S3_ASSETS_BUCKET_NAME = aws_s3_bucket.data.id
    MODELS_CONFIG_S3_OBJECT = aws_s3_object.models_config_internal.key
  }

  policy_statements = {
    ecs_list_tasks = {
      effect = "Allow"
      actions = ["ecs:ListTasks"]
      resources = ["*"]
    }

    ecs_run_task = {
      effect = "Allow"
      actions = ["ecs:RunTask"]
      resources = [for x in aws_ecs_task_definition.model_tasks: x.arn]
    }

    ecs_pass_role = {
      effect = "Allow"
      actions = ["iam:PassRole"]
      resources = [
        aws_iam_role.model_task.arn,
        module.ecs.task_exec_iam_role_arn
      ]
    }

    db_access = {
      effect = "Allow",
      actions = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
      ],
      resources = [aws_dynamodb_table.results_cache.arn]
    }

    s3_list = {
      effect = "Allow",
      actions = ["s3:ListBucket"],
      resources = [ aws_s3_bucket.data.arn ]
    }

    s3_read = {
      effect = "Allow",
      actions = ["s3:GetObject"],
      resources = [aws_s3_object.models_config_internal.arn]
    }

    sqs_send = {
      effect = "Allow"
      actions = ["sqs:SendMessage"]
      resources = [for x in aws_sqs_queue.model_queues: x.arn]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}

output "polling_lambda" {
  value = module.polling_lambda.lambda_function_name
}
