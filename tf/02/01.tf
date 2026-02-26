data "aws_vpc" "vpc" {
  id = data.terraform_remote_state.containers.outputs["vpc_id"]
}

data "aws_security_group" "vpc_default_security_group" {
  id = data.terraform_remote_state.containers.outputs["vpc_default_security_group_id"]
}

data "aws_subnet" "private_subnets" {
  for_each = toset(data.terraform_remote_state.containers.outputs["vpc_private_subnet_ids"])
  id       = each.value
}

data "aws_subnet" "public_subnets" {
  for_each = toset(data.terraform_remote_state.containers.outputs["vpc_public_subnet_ids"])
  id       = each.value
}

data "aws_efs_file_system" "efs" {
  file_system_id = data.terraform_remote_state.containers.outputs["efs_id"]
}

data "aws_efs_access_point" "efs_assets_ro" {
  access_point_id = data.terraform_remote_state.containers.outputs["efs_assets_ro_id"]
}

data "aws_security_group" "lambda_sg" {
  id = data.terraform_remote_state.containers.outputs["lambda_sg"]
}

data "aws_iam_policy" "efs_assets_ro" {
  arn = data.terraform_remote_state.containers.outputs["efs_assets_ro_iam_policy_arn"]
}

data "aws_ecr_image" "environment_image" {
  repository_name = data.terraform_remote_state.containers.outputs["environment_ecr_name"]
  image_tag       = var.git_tag
}
