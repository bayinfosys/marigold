module "acm" {
  source  = "terraform-aws-modules/acm/aws"
  version = "~> 5.0"

  domain_name = var.project_domain
  zone_id     = data.aws_route53_zone.primary.zone_id

  subject_alternative_names = concat([
      local.api_domain,
      local.web_domain
  ])

  validation_method = "DNS"

  tags = merge(var.project_tags)
}

module "acm_us_east" {
  source  = "terraform-aws-modules/acm/aws"
  version = "~> 5.0"

  providers = {
    aws = aws.us_east
  }

  domain_name = var.project_domain
  zone_id     = data.aws_route53_zone.primary.zone_id

  subject_alternative_names = concat([
      local.api_domain,
      local.web_domain
  ])

  validation_method = "DNS"

  tags = merge(var.project_tags)
}
