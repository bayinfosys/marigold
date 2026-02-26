#
# Static assets uploaded to the assets S3 bucket.
# These are consumed by:
#   - the cache builder EC2 instance (models.json, scripts)
#   - the API models endpoint (models.json, models.yaml)
#   - any tooling that needs the canonical model list
#
# Source files:
#   assets/models.yaml                       -- committed, hand-maintained
#   scripts/cache_models.py                  -- cache manager orchestrator
#   package/src/models/cache_model.py        -- per-model HuggingFace downloader
#
# models.json is generated from models.yaml by Terraform's yamldecode().
# No external script or build step is required for the conversion.
#

locals {
  models_yaml_raw     = file("${path.module}/../assets/models.yaml")
  models_yaml_decoded = yamldecode(local.models_yaml_raw)
}

#
# Model catalogue
#

resource "aws_s3_object" "models_yaml" {
  bucket       = aws_s3_bucket.data.id
  key          = "models.yaml"
  content      = local.models_yaml_raw
  content_type = "application/x-yaml"
  etag         = md5(local.models_yaml_raw)

  tags = var.project_tags
}

resource "aws_s3_object" "models_json" {
  bucket       = aws_s3_bucket.data.id
  key          = "models.json"
  content      = jsonencode(local.models_yaml_decoded)
  content_type = "application/json"
  etag         = md5(jsonencode(local.models_yaml_decoded))

  tags = var.project_tags
}

#
# Cache builder scripts
#

resource "aws_s3_object" "cache_model_script" {
  bucket       = aws_s3_bucket.data.id
  key          = "scripts/cache_model.py"
  content      = file("${path.module}/../../package/src/models/cache_model.py")
  content_type = "text/x-python"
  etag         = filemd5("${path.module}/../../package/src/models/cache_model.py")

  tags = var.project_tags
}

#
# Outputs consumed by tf/tools/cache-builder via remote state
#

output "models_yaml_s3_key" {
  description = "S3 key for models.yaml"
  value       = aws_s3_object.models_yaml.key
}

output "models_json_s3_key" {
  description = "S3 key for models.json (consumed by cache builder and API)"
  value       = aws_s3_object.models_json.key
}

output "models_json_s3_etag" {
  description = "ETag of models.json -- changes when models.yaml changes, triggering cache builder instance replacement"
  value       = aws_s3_object.models_json.etag
}

output "cache_models_script_s3_key" {
  description = "S3 key for cache_models.py (cache builder orchestrator)"
  value       = aws_s3_object.cache_models_script.key
}

output "cache_model_script_s3_key" {
  description = "S3 key for cache_model.py (per-model HuggingFace downloader)"
  value       = aws_s3_object.cache_model_script.key
}
