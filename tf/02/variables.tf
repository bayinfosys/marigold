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
  description = "Git tag identifying the deployment."
  type        = string
}

variable "hf_token" {
  description = "HuggingFace API token for gated models (hf_token_required: true)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "lambda_runtime" {
  type    = string
  default = "python3.13"
}

variable "models" {
  description = "Model container definitions, generated from assets/models.yaml."
  type = map(object({
    memory_res            = optional(number, 4096)
    gpu_tier              = optional(string, "none")
    gpu_units             = optional(number, 0)
    timeout               = optional(number, 600)
    idle_timeout          = optional(number, 600)
    auth_required         = optional(bool, false)
    provider              = optional(string, "huggingface")
    environment_variables = optional(map(string), {})
  }))
}

variable "efs_mount_point" {
  description = "Path inside the cache builder container where EFS is mounted for model weights."
  default     = "/mnt/shared"
}

variable "efs_model_cache_path" {
  description = "Path inside the cache builder container where EFS is mounted for model weights."
  default     = "/mnt/shared/models"
}

variable "capacity_provider_gpu_sm" {
  description = "ECS capacity provider name for small GPU instances (T4)"
  type        = string
  default     = "gpu-sm"
}

variable "capacity_provider_gpu_lrg" {
  description = "ECS capacity provider name for large GPU instances (A10G)"
  type        = string
  default     = "gpu-lrg"
}

variable "capacity_provider_big_cpu" {
  description = "ECS capacity provider name for large CPU instances"
  type        = string
  default     = "big-cpu"
}

variable "anonchat_model" {
  description = "Model name for the anon chat service. Must be cached on EFS."
  type        = string
  default     = "meta-llama/llama-3.1-8b-instruct"
}
