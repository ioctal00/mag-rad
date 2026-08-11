output "region" {
  value = module.region.region_code
}

output "vpc_cidr" {
  value = module.region.vpc_cidr
}

output "vpc_id" {
  value = module.region.vpc_id
}

output "load_balancer_ipv4" {
  value = module.region.load_balancer_ipv4
}

output "coordinator_public_ip" {
  value = module.region.coordinator_public_ip
}

output "coordinator_private_ip" {
  value = module.region.coordinator_private_ip
}

output "worker_public_ips" {
  value = module.region.worker_public_ips
}

output "worker_private_ips" {
  value = module.region.worker_private_ips
}

output "backend_public_ips" {
  value = module.region.backend_public_ips
}

output "web_portal_public_ip" {
  value = module.region.web_portal_public_ip
}

output "web_portal_private_ip" {
  value = module.region.web_portal_private_ip
}

output "ssh_commands" {
  value = module.region.ssh_commands
}
