resource "aws_security_group" "lambda_sg" {
  name        = join("-", [var.org_name, var.project_name, var.env, "lambda-sg"])
  description = "Security group for Lambda functions"
  vpc_id      = module.vpc.vpc_id

  egress {
    # TODO(prod): restrict to VPC CIDR only.
    # Lambda functions communicate exclusively via VPC endpoints:
    #   - ECR (443) for image pulls (ecr.api, ecr.dkr endpoints)
    #   - S3 (443) for model outputs and assets (S3 gateway endpoint)
    #   - DynamoDB (443) for results cache and usage table
    #   - SQS (443) for work queue access
    # Replace with: cidr_blocks = [data.aws_vpc.vpc.cidr_block] and
    # explicit port/protocol rules per destination once endpoints are validated.
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "TEMPORARY: allow all outbound. Restrict before production."
  }

  tags = var.project_tags
}
