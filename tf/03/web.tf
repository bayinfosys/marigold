locals {
  web_domain  = "marigold.run"
  mime_types = {
    html  = "text/html"
    css   = "text/css"
    eot   = "application/vnd.ms-fontobject"
    woff  = "font/woff"
    woff2 = "font/woff2"
    js    = "application/javascript"
    json  = "application/json"
    png   = "image/png"
    jpg   = "image/jpeg"
    jpeg  = "image/jpeg"
    svg   = "image/svg+xml"
    ttf   = "application/x-font-ttf"
    txt   = "text/plain"
    webp  = "image/webp"
  }
}

data "aws_route53_zone" "marigold" {
  zone_id = "Z02653181KLDW6FBR1WRD"
}

resource "aws_s3_bucket" "web" {
  bucket_prefix = join("-", [var.project_name, var.env, "web"])
}

resource "aws_cloudfront_origin_access_identity" "web" {
  comment = "origin access identity created by terraform"
}

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "PublicReadGetObject"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "AWS"
      identifiers = [aws_cloudfront_origin_access_identity.web.iam_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web.json
}

resource "aws_cloudfront_distribution" "s3_distribution" {
  origin {
    domain_name = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id   = aws_s3_bucket.web.id

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.web.cloudfront_access_identity_path
    }
  }

  enabled             = true
  is_ipv6_enabled     = true
  comment             = join("-", [var.project_name, var.env])
  default_root_object = "index.html"

  aliases = [local.web_domain, "www.${local.web_domain}"]

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = aws_s3_bucket.web.id

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
    compress               = true
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  price_class = "PriceClass_100"

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = module.acm_marigold_us_east.acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = var.project_tags
}

resource "aws_s3_object" "web_landing_page_files" {
  for_each = fileset("${path.module}/../../html", "**")

  bucket = aws_s3_bucket.web.bucket
  key    = each.value
  source = "${path.module}/../../html/${each.value}"

  content_type = lookup(
    local.mime_types,
    split(".", each.value)[length(split(".", each.value)) - 1],
    "application/octet-stream"
  )

  etag = filemd5("${path.module}/../../html/${each.value}")
}

resource "aws_route53_record" "apex" {
  zone_id = data.aws_route53_zone.marigold.zone_id
  name    = local.web_domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.s3_distribution.domain_name
    zone_id                = aws_cloudfront_distribution.s3_distribution.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www" {
  zone_id = data.aws_route53_zone.marigold.zone_id
  name    = "www.${local.web_domain}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.s3_distribution.domain_name
    zone_id                = aws_cloudfront_distribution.s3_distribution.hosted_zone_id
    evaluate_target_health = false
  }
}
