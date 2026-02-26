variable "org_name" {
  type = string
}

variable "project_name" {
  type = string
}

variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "models" {
  description = "definitions of the model containers"
  type = map(object({
    image = string
    handler = string
    memory_size = optional(number, 9216)
    timeout = optional(number, 300)
    environment_variables = optional(map(string), {})
    vector_size = optional(number, 0)
    log_level = optional(string, "INFO")
  }))
}

variable "project_tags" {
  description = "common tags for all project resources"
  type = map
  default = {}
}

variable "env" {
  type = string
}

variable "git_tag" {
  description = "git tag for this deployment"
  type = string
}

variable "lambda_runtime" {
  type = string
  default = "python3.13"
}
