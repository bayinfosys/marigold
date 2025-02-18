variable "org_name" {
  type = string
}

variable "project_name" {
  type = string
}

variable "project_tags" {
  description = "common tags for all project resources"
  type        = map(any)
  default     = {}
}

variable "env" {
  type = string
}
