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
    Only needs enough RAM for the downloader process itself -- models are
    streamed to EFS and never loaded into memory. t3.large is sufficient
    for all current models. Use r5.xlarge only if a model's download
    process requires more than 8 GB RAM.
  EOT
  type    = string
  default = "t3.large"
}

variable "max_runtime_seconds" {
  description = <<-EOT
    Maximum time in seconds the cache builder is allowed to run before the
    instance self-terminates. Prevents indefinite hangs from stalled downloads.
    Default is 4 hours. Increase for very large model sets.
  EOT
  type    = number
  default = 14400
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

variable "models_yaml_key" {
  description = "S3 key for the models YAML file to use for this cache run."
  type        = string
  default     = "models.yaml"
}

variable "ssh_allowed_cidr" {
  description = "CIDR block allowed to SSH to the cache builder instance."
  type        = string
  default     = ""
}
