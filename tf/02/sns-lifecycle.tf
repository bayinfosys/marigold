resource "aws_sns_topic" "lifecycle" {
  name = join("-", [var.org_name, var.project_name, var.env, "lifecycle"])
  tags = var.project_tags
}
