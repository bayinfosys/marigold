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

variable "private_vpc_cloudwatch" {
  description = "Enable or disable the CloudWatch VPC endpoint"
  type        = bool
  default     = false
}

variable "git_tag" {
  description = "git tag for this deployment"
  type = string
}

variable "availability_zones" {
  description = "Availability zones to deploy into. Single AZ reduces cost during testing."
  type        = list(string)
  default     = ["eu-west-2a"]
}

variable "private_subnets" {
  description = "CIDR blocks for private subnets, one per AZ."
  type        = list(string)
  default     = ["10.10.102.0/24"]
}

variable "public_subnets" {
  description = "CIDR blocks for public subnets, one per AZ."
  type        = list(string)
  default     = ["10.10.1.0/24"]
}

variable "models" {
  description = "Model definitions. Declared here so models.tfvars can be passed uniformly to all layers."
  type        = any
  default     = {}
}
