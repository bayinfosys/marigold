# ---------------------------------------------------------------------------
# Usage tracking table.
#
# Append-only event log for API access events.
# Written to by api_logger_lambda in layer 03.
# Read by api_usage_lambda in layer 03.
#
# Row structure:
#   PK: METRIC#RAW#USER#{api_key_id}
#   SK: DATE#{timestamp}#REQ#{request_id}
# ---------------------------------------------------------------------------

module "usage_table" {
  source = "terraform-aws-modules/dynamodb-table/aws"

  name      = join("-", [var.org_name, var.project_name, var.env, "usage"])
  hash_key  = "PK"
  range_key = "SK"

  attributes = [
    { name = "PK", type = "S" },
    { name = "SK", type = "S" },
  ]

  ttl_attribute_name = "ttl"
  ttl_enabled        = true

  stream_enabled = true
  stream_view_type = "NEW_IMAGE"

  tags = var.project_tags
}

output "usage_table_id" {
  value = module.usage_table.dynamodb_table_id
}

output "usage_table_arn" {
  value = module.usage_table.dynamodb_table_arn
}
