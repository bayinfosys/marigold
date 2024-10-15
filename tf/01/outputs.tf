output "vpc_id" {
  value = module.vpc.vpc_id
}

output "vpc_default_security_group_id" {
  value = module.vpc.default_security_group_id
}

output "vpc_private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "vpc_public_subnet_ids" {
  value = module.vpc.public_subnets
}

output "efs_id" {
  value = module.efs.id
}

output "efs_assets_ro_id" {
  value = module.efs.access_points["assets_ro"].id
}

output "efs_assets_ro_iam_policy_arn" {
  value = aws_iam_policy.efs_access_policy.arn
}

output "lambda_sg" {
  value = aws_security_group.lambda_sg.id
}
