# -----------------------------------------------------------------------------
# Dashboard: bucket S3 privado + CloudFront con Origin Access Control (OAC)
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "dashboard" {
  bucket_prefix = "${var.project}-dashboard-"
  force_destroy = true # permite "terraform destroy" aunque el bucket tenga archivos
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "index" {
  bucket       = aws_s3_bucket.dashboard.id
  key          = "index.html"
  source       = "${path.module}/../../dashboard/index.html"
  etag         = filemd5("${path.module}/../../dashboard/index.html")
  content_type = "text/html; charset=utf-8"
}

# config.js se genera con la URL real de la API: el HTML no lleva URLs fijas.
resource "aws_s3_object" "config" {
  bucket       = aws_s3_bucket.dashboard.id
  key          = "config.js"
  content_type = "application/javascript"
  content = templatefile("${path.module}/templates/config.js.tftpl", {
    api_url   = aws_apigatewayv2_stage.default.invoke_url
    device_id = var.thing_name
  })
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  count                             = var.enable_cloudfront ? 1 : 0
  name                              = "${var.project}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "dashboard" {
  count               = var.enable_cloudfront ? 1 : 0
  enabled             = true
  comment             = "Dashboard del pluviometro gravimetrico IoT"
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # solo Norteamerica y Europa: mas barato

  origin {
    domain_name              = aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_id                = "s3-dashboard"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard[0].id
  }

  default_cache_behavior {
    target_origin_id       = "s3-dashboard"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    # Politica administrada "CachingDisabled": durante el desarrollo cada cambio se ve de inmediato.
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Solo CloudFront (esta distribucion) puede leer el bucket.
resource "aws_s3_bucket_policy" "dashboard" {
  count  = var.enable_cloudfront ? 1 : 0
  bucket = aws_s3_bucket.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontOAC"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.dashboard.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.dashboard[0].arn }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.dashboard]
}
