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
    cpu_size              = optional(number, 1024)
    memory_size           = optional(number, 8192)
    requires_gpu          = optional(bool, false)
    timeout               = optional(number, 300)
    idle_timeout          = optional(number, 0)
    auth_required         = optional(bool, false)
    provider              = optional(string, "huggingface")
    environment_variables = optional(map(string), {})
  }))
}

variable "enable_gpu_services" {
  description = <<-EOT
    Controls whether ECS services are created for GPU models.
    Set to true only when the GPU capacity provider has active EC2 instances
    and the cluster is confirmed to be accepting EC2 tasks.
    GPU task definitions and SQS queues are always created regardless of
    this flag -- only the services are gated.
  EOT
  type    = bool
  default = false
}
