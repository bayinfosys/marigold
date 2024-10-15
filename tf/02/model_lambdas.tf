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
  description   = "${var.project_name}-${var.env}-${each.key}"

  cloudwatch_logs_retention_in_days = 5

  create_package = false

  image_uri    = data.aws_ecr_image.images[each.value.image].image_uri
  package_type = "Image"

  memory_size = each.value.memory_size
  timeout     = each.value.timeout
  image_config_command = [each.value.command]
  image_config_entry_point = ["/lambda-entrypoint.sh"]

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
    }
  }

  attach_policy_statements = true

  # tags
  tags = merge(var.project_tags, {
    Container = each.key
    Model     = reverse(split("/", each.key))[0]
  })
}
