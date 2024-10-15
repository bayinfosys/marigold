resource "aws_security_group" "lambda_sg" {
  name = join("-", [var.org_name, var.project_name, var.env, "lambda-sg"])

  description = "Security group for Lambda function"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.project_tags
}
