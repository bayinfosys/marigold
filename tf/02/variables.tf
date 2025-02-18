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

variable "project_tags" {
  description = "common tags for all project resources"
  type = map
  default = {}
}

variable "env" {
  type = string
}
