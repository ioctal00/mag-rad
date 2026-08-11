terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  fqdn = "${var.record_name}.${var.root_domain}"
}

resource "aws_route53_record" "eu" {
  zone_id        = var.zone_id
  name           = local.fqdn
  type           = "A"
  ttl            = var.ttl
  records        = [var.eu_lb_ip]
  set_identifier = "eu"

  latency_routing_policy {
    region = var.eu_latency_region
  }
}

resource "aws_route53_record" "us" {
  zone_id        = var.zone_id
  name           = local.fqdn
  type           = "A"
  ttl            = var.ttl
  records        = [var.us_lb_ip]
  set_identifier = "us"

  latency_routing_policy {
    region = var.us_latency_region
  }
}

