module "latency_dns" {
  count  = var.create_api_record ? 1 : 0
  source = "../modules/route53_latency_dns"

  zone_id           = var.zone_id
  root_domain       = var.root_domain
  record_name       = var.record_name
  eu_lb_ip          = var.eu_lb_ip
  us_lb_ip          = var.us_lb_ip
  ttl               = var.ttl
  eu_latency_region = var.eu_latency_region
  us_latency_region = var.us_latency_region
}

