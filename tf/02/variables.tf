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

variable "container_tag" {
  description = "deployment distribution version (git tag)"
  type = string
}

variable "containers" {
  description = "container definitions for the lambda function"
  type = list(string)
}

variable "available_models" {
  description = "models available from the efs cache"
  type = map(object({
    model_type = string
  }))
}

variable "model_lambdas" {
  description = "definitions of the lambda functions"
  type = map(object({
    image = string
    command = optional(string, "main.handler")
    memory_size = optional(number, 3000)
    timeout = optional(number, 300)
    environment_variables = optional(map(string), {})
    vector_size = optional(number, 0)
  }))
}

variable "db_lambdas" {
  description = "definitions of the lambda functions"
  type = map(object({
    image = string
    command = string
    memory_size = number
    timeout = number
    environment_variables = optional(map(string), {})
  }))
}

variable "tool_lambdas" {
  description = "definitions of the lambda functions"
  type = map(object({
    image = string
    command = optional(string, "main.lambda_handler")
    memory_size = optional(number)
    timeout = optional(number)
    environment_variables = optional(map(string), {})
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
