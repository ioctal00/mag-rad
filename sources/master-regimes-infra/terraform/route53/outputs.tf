output "api_fqdn" {
  value = var.create_api_record ? module.latency_dns[0].fqdn : null
}

