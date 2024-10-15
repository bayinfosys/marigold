resource "aws_ecr_repository" "containers" {
  for_each = toset(var.containers)

  name                 = join("/", [var.org_name, var.project_name, each.key])
  image_tag_mutability = "IMMUTABLE"

  # delete the repo even if images are inside
  force_delete = true

  tags = var.project_tags
}

resource "aws_ecr_lifecycle_policy" "delete" {
  for_each = aws_ecr_repository.containers

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1,
        description  = "delete untagged images",
        selection = {
          tagStatus   = "untagged",
          countType   = "imageCountMoreThan",
          countNumber = 1
        },
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "delete old images",
        selection = {
          tagStatus      = "tagged",
          tagPatternList = ["*"],
          countType      = "imageCountMoreThan",
          countNumber    = 5
        },
        action = {
          type = "expire"
        }
      }
    ]
  })
}
