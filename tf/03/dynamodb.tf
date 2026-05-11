resource "aws_dynamodb_table" "users" {
  name         = join("-", [var.org_name, var.project_name, var.env, "users"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

#  deletion_protection_enabled = true

#  lifecycle {
#    prevent_destroy = true
#  }

  tags = var.project_tags
}
