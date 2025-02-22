#
# lambda for each model
# - based on a common model
# - envvars sets the actual model
# - model binary/packages are loaded from efs
#
module "model_lambdas" {
  for_each = var.model_lambdas

  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, replace(each.key, "/", "-")])
  description = each.value.environment_variables["MODELNAME"]

  cloudwatch_logs_retention_in_days = 5

  runtime = "python3.12"
  source_path = [
    join("/", [path.module, "..", "..", "package", "src"]),
    {
      path = join("/", [path.module, "lambdas", "lame", "lame"])
    }
  ]
  handler = each.value.command

  memory_size = each.value.memory_size
  timeout     = each.value.timeout

  # vpc
  vpc_subnet_ids         = [for x in data.aws_subnet.private_subnets: x.id]
  vpc_security_group_ids = [data.aws_security_group.lambda_sg.id]
  attach_network_policy  = true

  # efs
  file_system_arn              = data.aws_efs_access_point.efs_assets_ro.arn
  file_system_local_mount_path = "/mnt/shared"

  # efs location is passed via envars
  environment_variables = merge(each.value.environment_variables, {
    CACHE_DIR="/mnt/shared/models"
    HF_HUB_CACHE="/mnt/shared/models"
    PYTHONPATH="/usr/local/lib/python3.12:/mnt/shared/packages/lib/python3.12/site-packages"
    LAME_PATH="/var/task/lame"
    HF_HUB_DISABLE_PROGRESS_BARS="1"
    HF_HUB_DISABLE_TELEMETRY="1"
    HF_HOME="/tmp"
    HF_HUB_OFFLINE="1"
    LOAD_IN_4BIT="0"
    REMOTE_CODE="0"
    USE_FAST="0"
#    METRICS_QUEUE_URL=aws_sqs_queue.usage.url
    DYNAMODB_USAGE_TABLE=module.usage_table.dynamodb_table_id
  })

  # FIXME: use the efs_access_policy from 01
  policy_statements = {
    efs_access = {
      effect = "Allow"
      actions = [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientRead"
      ],
      resources = [data.aws_efs_access_point.efs_assets_ro.arn]
    },
#    sqs_send = {
#      effect    = "Allow",
#      actions   = ["sqs:SendMessage"],
#      resources = [aws_sqs_queue.usage.arn]
#    }
    dynamodb_write = {
      effect = "Allow"
      actions = [
        "dynamodb:PutItem",
      ]
      resources = [
        module.usage_table.dynamodb_table_arn
      ]
    }
  }

  attach_policy_statements = true

  # tags
  tags = merge(var.project_tags, {
    Container = each.key
    Model     = reverse(split("/", each.key))[0]
  })
}
