#
# list the files on the efs disk
#
module "list_efs" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.7.0"

  function_name = join("-", [var.org_name, var.project_name, var.env, "list-efs"])
  description   = "${var.project_name}-${var.env}-list-efs"

  cloudwatch_logs_retention_in_days = 5

  runtime     = "python3.11"
  source_path = join("/", [path.module, "lambdas", "list-efs", "main.py"])
  handler     = "main.handler"
  timeout     = 900

  # vpc
  vpc_subnet_ids         = module.vpc.private_subnets
  vpc_security_group_ids = [aws_security_group.lambda_sg.id]

  attach_network_policy = true

  # efs
  file_system_arn              = module.efs.access_points["assets_ro"].arn
  file_system_local_mount_path = "/mnt/shared"

  environment_variables = {
    SHARED_PATH = "/mnt/shared/"
  }

  policy_statements = {
    efs_access = {
      effect = "Allow"
      actions = [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientRootAccess"
      ],
      resources = [module.efs.access_points["assets_ro"].arn]
    }
  }

  attach_policy_statements = true

  tags = var.project_tags
}
