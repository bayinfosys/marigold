module "tool_lambdas" {
  for_each = var.tool_lambdas

  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "tools", each.key])
  description   = "${var.project_name}-${var.env}-${each.key}"

  cloudwatch_logs_retention_in_days = 5

  create_package = false

  environment_variables = each.value.environment_variables

  image_uri    = data.aws_ecr_image.images[each.value.image].image_uri
  package_type = "Image"

  image_config_entry_point    = ["/lambda-entrypoint.sh"]
  image_config_command = [each.value.command]
  memory_size          = each.value.memory_size
  timeout              = each.value.timeout

  policy_statements = {
    batch_job = {
      effect = "Allow"
      actions = [
        "batch:SubmitJob"
      ]
      resources = [
        "*"
      ]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}
