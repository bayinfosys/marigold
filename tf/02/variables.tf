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
    memory_size           = optional(number, 9216)
    timeout               = optional(number, 300)
    idle_timeout          = optional(number, 0)
    auth_required         = optional(bool, false)
    environment_variables = optional(map(string), {})
  }))
}
