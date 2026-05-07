locals {
  api_domain = "api.${var.env}.${var.project_domain}"
  #web_domain = "web.${var.env}.${var.project_domain}"
}

data "aws_route53_zone" "primary" {
  zone_id = "Z3EW1J42ZXU0NO"
}

resource "aws_api_gateway_domain_name" "domain" {
  domain_name              = local.api_domain
  certificate_arn          = module.acm_us_east.acm_certificate_arn
  security_policy          = "TLS_1_2"

  endpoint_configuration {
    types = ["EDGE"]
  }
}

resource "aws_route53_record" "api_gateway" {
  zone_id = data.aws_route53_zone.primary.zone_id
  name    = local.api_domain
  type    = "A"

  alias {
    name                   = aws_api_gateway_domain_name.domain.cloudfront_domain_name
    zone_id                = aws_api_gateway_domain_name.domain.cloudfront_zone_id
    evaluate_target_health = false
  }

  allow_overwrite = true
}

output "api_endpoint" {
  description = "api endpoint for frontend"
  value       = local.api_domain
}
