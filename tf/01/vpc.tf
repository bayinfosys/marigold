#
# lambda/efs requires a vpc
#
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = join("-", [var.org_name, var.project_name, var.env, "vpc"])
  cidr = "10.10.0.0/16"

  azs             = ["eu-west-2a"]
  private_subnets = ["10.10.102.0/24"]
  public_subnets  = ["10.10.1.0/24"]

  # TODO: only enable this when the cache-buidler instance is running
  #enable_nat_gateway = true
  #single_nat_gateway = true
  #map_public_ip_on_launch = true

  enable_dns_hostnames = true
  enable_dns_support   = true

  create_flow_log_cloudwatch_log_group = false
  create_flow_log_cloudwatch_iam_role  = false
  enable_flow_log                      = false
}

data "aws_iam_policy_document" "generic_endpoint_policy" {
  statement {
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "aws:SourceVpc"

      values = [module.vpc.vpc_id]
    }
  }
}

resource "aws_vpc_endpoint" "cloudwatch" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.eu-west-2.logs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = module.vpc.private_subnets

  security_group_ids = [
    module.vpc.default_security_group_id
  ]

  tags = merge(var.project_tags, {
    Name = join("-", [var.org_name, var.project_name, var.env, "cloudwatch"])
  })
}

#
# sg rules
#
resource "aws_vpc_security_group_egress_rule" "allow_all_out" {
  security_group_id = module.vpc.default_security_group_id

  description = "allow all traffic out of the subnet"

  cidr_ipv4 = "0.0.0.0/0"
  #  from_port   = 0
  #  to_port     = 0
  ip_protocol = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "ecr" {
  security_group_id = module.vpc.default_security_group_id

  description = "allow traffic from private subnet ips (ENI) on 443 (ecr,dynamodb,etc)"

  #  cidr_ipv4 = module.vpc.private_subnets_cidr_blocks[0]

  #  from_port   = 443
  #  to_port     = 443
  #  ip_protocol = "tcp"
  cidr_ipv4 = "0.0.0.0/0"
  #  from_port   = 0
  #  to_port     = 0
  ip_protocol = "-1"
}
