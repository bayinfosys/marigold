#
# model/packages bucket
#
resource "aws_s3_bucket" "data" {
  bucket_prefix = join("-", [var.org_name, var.project_name, var.env, "assets"])

  tags = var.project_tags
  force_destroy = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "Move to STANDARD_IA after 30 days"
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

#
# model outputs
#
resource "aws_s3_bucket" "model_outputs" {
  bucket_prefix = join("-", [var.org_name, var.project_name, var.env, "model-outputs"])
  tags          = var.project_tags
  force_destroy  = true
}

resource "aws_s3_bucket_lifecycle_configuration" "model_outputs" {
  bucket = aws_s3_bucket.model_outputs.id

  rule {
    id     = "Move to STANDARD_IA after 30 days"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

output "model_outputs_bucket_name" {
  value = aws_s3_bucket.model_outputs.id
}

output "model_outputs_bucket_arn" {
  value = aws_s3_bucket.model_outputs.arn
}

output "asset_bucket_arn" {
  description = "ARN of the assets S3 bucket (used by cache builder IAM policy)"
  value       = aws_s3_bucket.data.arn
}
