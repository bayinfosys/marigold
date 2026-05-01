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

output "efs_assets_rw_id" {
  description = "EFS read-write access point ID (used by the cache builder for mounting)"
  value       = module.efs.access_points["assets_rw"].id
}

output "efs_assets_rw_arn" {
  description = "EFS read-write access point ARN (used by the cache builder IAM policy)"
  value       = module.efs.access_points["assets_rw"].arn
}

output "efs_dns_name" {
  description = "EFS file system DNS name (used by the cache builder for mounting)"
  value       = module.efs.dns_name
}

output "efs_file_system_id" {
  description = "EFS file system ID (used by the cache builder for mounting)"
  value       = module.efs.id
}

output "ecr_registry" {
  description = "ECR registry URL for this account and region"
  value       = split("/", module.ecr.repository_url)[0]
}

output "environment_ecr_url" {
  description = "Full ECR repository URL for the environment image"
  value       = module.ecr.repository_url
}

output "environment_ecr_name" {
  value = module.ecr.repository_name
}

output "environment_ecr_arn" {
  description = "ARN of the environment ECR repository"
  value       = module.ecr.repository_arn
}
