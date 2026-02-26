variable "org_name" {
  type = string
}

variable "project_name" {
  type = string
}

variable "project_domain" {
  type = string
}

variable "project_tags" {
  description = "common tags for all project resources"
  type = map
  default = {}
}

variable "env" {
  type = string
}

variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "models" {
  description = "definitions of the model containers"
  type = any
}

variable "git_tag" {
  description = "git tag for this deployment"
  type = string
}

variable "master_key_email" {
  description = "email address for the default master API key"
  type        = string
  default     = "ed@bayis.co.uk"
}

variable "lambda_runtime" {
  type = string
  default = "python3.13"
}
