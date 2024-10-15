#
# model/packages bucket
#
resource "aws_s3_bucket" "data" {
  bucket_prefix = join("-", [var.org_name, var.project_name, var.env, "assets"])

  tags = var.project_tags
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "Move to STANDARD_IA after 10 days"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

output "asset_bucket_name" {
  value = aws_s3_bucket.data.id
}
