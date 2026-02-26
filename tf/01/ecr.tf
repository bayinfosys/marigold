module "ecr" {
  source = "terraform-aws-modules/ecr/aws"

  repository_name = join("/", [var.org_name, var.project_name, "environment"])

  #repository_read_write_access_arns = ["arn:aws:iam::012345678901:role/terraform"]

  repository_lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1,
        description  = "Keep last 10 images",
        selection = {
          tagStatus     = "tagged",
          tagPrefixList = ["v"],
          countType     = "imageCountMoreThan",
          countNumber   = 10
        },
        action = {
          type = "expire"
        }
      }
    ]
  })

  tags = var.project_tags
}

output "environment_ecr_name" {
  value = module.ecr.repository_name
}
