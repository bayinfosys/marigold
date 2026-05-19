resource "aws_dynamodb_table" "results_cache" {
  name         = join("-", [var.org_name, var.project_name, var.env, "results-cache"])
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK" # userid
    type = "S"
  }

  attribute {
    name = "SK" # messageid
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.project_tags
}


resource "aws_dynamodb_table" "events" {
  name         = join("-", [var.org_name, var.project_name, var.env, "events"])
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

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.project_tags
}
