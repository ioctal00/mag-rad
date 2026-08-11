output "environment" {
  description = "Environment name for this regional stack."
  value       = var.environment
}

output "region_code" {
  description = "Vultr region code used by this stack."
  value       = var.region_code
}

output "vpc_id" {
  description = "Regional Vultr VPC identifier."
  value       = local.vpc_id
}

output "vpc_cidr" {
  description = "Regional VPC IPv4 CIDR."
  value       = local.vpc_cidr
}

output "load_balancer_ipv4" {
  description = "Regional load balancer IPv4 address."
  value       = try(vultr_load_balancer.web[0].ipv4, null)
}

output "coordinator_public_ip" {
  description = "Public IPv4 address of the Citus coordinator."
  value       = local.coordinator_public_ip
}

output "coordinator_public_ipv6" {
  description = "Public IPv6 address of the Citus coordinator."
  value       = local.coordinator_public_ipv6
}

output "coordinator_private_ip" {
  description = "Citus coordinator address used for regional DB traffic. For cloud instances this is the VPC IP; for bare metal this falls back to the public IPv4 because the provider does not expose the VPC IP."
  value       = local.coordinator_db_ip
}

output "worker_public_ips" {
  description = "Public IPv4 addresses of Citus worker nodes."
  value       = local.worker_public_ips
}

output "worker_private_ips" {
  description = "Citus worker addresses used for regional DB traffic. For cloud instances these are VPC IPs; for bare metal they fall back to public IPv4 addresses because the provider does not expose VPC IPs."
  value       = local.worker_db_ips
}

output "backend_public_ips" {
  description = "Public IPv4 addresses of backend nodes."
  value       = local.backend_public_ips
}

output "global_analytics_client_public_ip" {
  description = "Public IPv4 address of the optional global analytics client."
  value       = local.global_analytics_client_public_ip
}

output "global_analytics_client_public_ipv6" {
  description = "Public IPv6 address of the optional global analytics client."
  value       = local.global_analytics_client_public_ipv6
}

output "global_analytics_client_private_ip" {
  description = "Analytics client DB traffic address. For cloud instances attached to the VPC this is the VPC IP; for bare metal it falls back to public IPv4."
  value       = local.global_analytics_client_private_ip
}

output "global_analytics_client_attached_to_vpc" {
  description = "Whether the optional global analytics client is attached to the regional VPC."
  value       = var.global_analytics_client_enabled && var.global_analytics_client_attach_vpc
}

output "web_portal_public_ip" {
  description = "Public IPv4 address of the optional Pgweb/viewer web portal."
  value       = local.web_portal_public_ip
}

output "web_portal_private_ip" {
  description = "VPC IPv4 address of the optional Pgweb/viewer web portal."
  value       = local.web_portal_private_ip
}

output "ssh_commands" {
  description = "Convenience SSH commands for all instances."
  value = concat(
    local.coordinator_public_ip != null ? ["ssh root@${local.coordinator_public_ip}"] : [],
    [for ip in local.worker_public_ips : "ssh root@${ip}"],
    [for ip in local.backend_public_ips : "ssh root@${ip}"],
    local.web_portal_public_ip != null ? ["ssh root@${local.web_portal_public_ip}"] : [],
    local.global_analytics_client_public_ip != null ? ["ssh root@${local.global_analytics_client_public_ip}"] : []
  )
}
