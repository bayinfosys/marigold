# Primary cert (regional) - covers your api/web subdomains only, no marigold
module "acm" {
  source  = "terraform-aws-modules/acm/aws"
  version = "~> 5.0"

  domain_name = var.project_domain
  zone_id     = data.aws_route53_zone.primary.zone_id

  subject_alternative_names = [
    local.api_domain,
    #local.web_domain
  ]

  validation_method = "DNS"
  tags              = var.project_tags
}

# Primary cert (us-east-1) - same, no marigold
module "acm_us_east" {
  source  = "terraform-aws-modules/acm/aws"
  version = "~> 5.0"

  providers = {
    aws = aws.us_east
  }

  domain_name = var.project_domain
  zone_id     = data.aws_route53_zone.primary.zone_id

  subject_alternative_names = [
    local.api_domain,
    #local.web_domain
  ]

  validation_method = "DNS"
  tags              = var.project_tags
}
