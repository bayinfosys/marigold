variable "org_name" {
  type = string
}

variable "project_name" {
  type = string
}

variable "env" {
  type = string
}

variable "project_tags" {
  type    = map(any)
  default = {}
}

variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "git_tag" {
  description = "Git tag identifying the deployment. Used for tagging the instance."
  type        = string
}

variable "hf_token" {
  description = "HuggingFace API token for downloading gated models."
  type        = string
  sensitive   = true
  default     = ""
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type for the cache builder.
    The instance must have enough RAM to load the largest model for caching.
    Sub-4B parameter models: r5.xlarge (32 GB) is sufficient.
    7B parameter models: r5.2xlarge (64 GB) is required.
  EOT
  type    = string
  default = "r5.xlarge"
}

variable "prune_cache" {
  description = <<-EOT
    Whether the cache builder should remove models from EFS that are no longer
    in models.yaml. Disabled by default to prevent accidental data loss.
    Set to true explicitly when you intend to free EFS space after removing models.
  EOT
  type    = bool
  default = false
}
