#
# lambda/efs requires a vpc
#
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = join("-", [var.org_name, var.project_name, var.env, "vpc"])
  cidr = "10.10.0.0/16"

  azs             = var.availability_zones
  private_subnets = var.private_subnets
  public_subnets  = var.public_subnets

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

module "vpc_endpoints" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "~> 5.8"

  vpc_id = module.vpc.vpc_id

  create_security_group      = true
  security_group_name_prefix = join("-", [var.project_name, var.env, "vpc-endpoints-"])
  security_group_description = "VPC endpoint security group"
  security_group_rules = {
    ingress_https = {
      description = "HTTPS from VPC"
      cidr_blocks = [module.vpc.vpc_cidr_block]
    }
  }

  endpoints = {
    ecr_api = {
      service             = "ecr.api"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ecr-api" }
    }
    ecr_dkr = {
      service             = "ecr.dkr"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ecr-dkr" }
    }
    logs = {
      #
      # cloudwatch interface for the private vpc
      #   NB: this costs money to have running (~£20pm)
      #   so we only enable it for debugging.
      #
      # this is disabled when var.private_vpc_cloudwatch is false
      #
      service             = "logs"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "logs" }
    }
    dynamodb = {
      service         = "dynamodb"
      service_type    = "Gateway"
      route_table_ids = module.vpc.private_route_table_ids
      tags            = { Name = "dynamodb" }
    }
    s3 = {
      service             = "s3"
      service_type        = "Interface"
      route_table_ids = module.vpc.private_route_table_ids
      tags            = { Name = "s3" }
    },
    sqs = {
      service             = "sqs"
      private_dns_enabled = true
      security_group_ids  = [module.vpc.default_security_group_id]
      subnet_ids          = module.vpc.private_subnets
      tags                = { Name = "sqs" }
    }
    sns = {
      service             = "sns"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "sns" }
    }
    ssm = {
      service             = "ssm"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ssm" }
    }
    ssmmessages = {
      service             = "ssmmessages"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ssmmessages" }
    }
    ec2messages = {
      service             = "ec2messages"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ec2messages" }
    }
    ecs = {
      service             = "ecs"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ecs" }
    }
    ecs_agent = {
      service             = "ecs-agent"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ecs-agent" }
    }
    ecs_telemetry = {
      service             = "ecs-telemetry"
      service_type        = "Interface"
      private_dns_enabled = true
      subnet_ids          = module.vpc.private_subnets
      security_group_ids  = [module.vpc.default_security_group_id]
      tags                = { Name = "ecs-telemetry" }
    }
  }

  tags = var.project_tags
}


#
# sg rules
#
resource "aws_vpc_security_group_egress_rule" "allow_all_out" {
  security_group_id = module.vpc.default_security_group_id

  # TODO(prod): restrict to VPC CIDR only once NAT gateway is confirmed not required.
  # Required outbound destinations are:
  #   - ECR (443) via ecr.api and ecr.dkr VPC endpoints
  #   - S3 (443) via S3 gateway endpoint
  #   - DynamoDB (443) via DynamoDB gateway endpoint
  #   - SQS (443) via SQS interface endpoint
  #   - EFS (2049) within private subnets
  # All of these are within the VPC, so cidr_ipv4 = module.vpc.vpc_cidr_block
  # is sufficient once the NAT gateway is removed.
  description = "TEMPORARY: allow all outbound. Restrict before production."
  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "vpc_internal" {
  security_group_id = module.vpc.default_security_group_id

  # TODO(prod): restrict to vpc_cidr_block and remove the catch-all below.
  # Inbound to the default SG is required from:
  #   - VPC endpoint ENIs (HTTPS/443) for ECR, S3, SQS, DynamoDB, CloudWatch
  #   - EFS mount traffic (NFS/2049) from private subnets (handled by efs module SG)
  # The efs module manages its own SG ingress rules (see efs.tf).
  description = "TEMPORARY: allow all inbound. Restrict before production."
  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}
