terraform {
  required_providers {
    vultr = {
      source = "vultr/vultr"
    }
  }
}

locals {
  name_prefix            = "${var.project_tag}-${var.environment}"
  all_tags               = distinct(concat([var.project_tag, var.environment, "master-thesis"], var.tags))
  use_instance_compute   = var.compute_resource_type == "instance"
  use_bare_metal_compute = var.compute_resource_type == "bare_metal"
  create_vpc             = var.existing_vpc_id == ""
  global_analytics_client_effective_resource_type = (
    var.global_analytics_client_resource_type != "" ? var.global_analytics_client_resource_type : var.compute_resource_type
  )
  use_instance_analytics   = local.global_analytics_client_effective_resource_type == "instance"
  use_bare_metal_analytics = local.global_analytics_client_effective_resource_type == "bare_metal"
  global_analytics_client_region_code = (
    var.global_analytics_client_region_code != "" ? var.global_analytics_client_region_code : var.region_code
  )
  coordinator_public_ip = try(concat(
    [for node in vultr_instance.coordinator : node.main_ip],
    [for node in vultr_bare_metal_server.coordinator : node.main_ip]
  )[0], null)
  coordinator_public_ipv6 = try(concat(
    [for node in vultr_instance.coordinator : node.v6_main_ip],
    [for node in vultr_bare_metal_server.coordinator : node.v6_main_ip]
  )[0], null)
  coordinator_db_ip = try(concat(
    [for node in vultr_instance.coordinator : node.internal_ip],
    [for node in vultr_bare_metal_server.coordinator : node.main_ip]
  )[0], null)
  worker_public_ips = concat(
    [for node in vultr_instance.worker : node.main_ip],
    [for node in vultr_bare_metal_server.worker : node.main_ip]
  )
  worker_db_ips = concat(
    [for node in vultr_instance.worker : node.internal_ip],
    [for node in vultr_bare_metal_server.worker : node.main_ip]
  )
  backend_public_ips = concat(
    [for node in vultr_instance.backend : node.main_ip],
    [for node in vultr_bare_metal_server.backend : node.main_ip]
  )
  global_analytics_client_public_ip = try(concat(
    [for node in vultr_instance.global_analytics_client : node.main_ip],
    [for node in vultr_bare_metal_server.global_analytics_client : node.main_ip]
  )[0], null)
  global_analytics_client_public_ipv6 = try(concat(
    [for node in vultr_instance.global_analytics_client : node.v6_main_ip],
    [for node in vultr_bare_metal_server.global_analytics_client : node.v6_main_ip]
  )[0], null)
  global_analytics_client_private_ip = try(concat(
    [for node in vultr_instance.global_analytics_client : node.internal_ip],
    [for node in vultr_bare_metal_server.global_analytics_client : node.main_ip]
  )[0], null)
  web_portal_public_ip  = try(vultr_instance.web_portal[0].main_ip, null)
  web_portal_private_ip = try(vultr_instance.web_portal[0].internal_ip, null)

  admin_cidr_map = {
    for idx, cidr in var.admin_ipv4_cidrs :
    format("admin-%02d", idx) => {
      subnet = split("/", cidr)[0]
      mask   = tonumber(split("/", cidr)[1])
    }
  }

  web_cidr_map = {
    for idx, cidr in var.web_ipv4_cidrs :
    format("web-%02d", idx) => {
      subnet = split("/", cidr)[0]
      mask   = tonumber(split("/", cidr)[1])
    }
  }

  external_db_cidr_map = {
    for cidr in distinct(concat(var.admin_ipv4_cidrs, var.db_access_ipv4_cidrs)) :
    cidr => {
      subnet = split("/", cidr)[0]
      mask   = tonumber(split("/", cidr)[1])
    }
  }
}

resource "vultr_ssh_key" "managed" {
  for_each = var.ssh_keys

  name    = "${local.name_prefix}-${each.key}"
  ssh_key = each.value
}

resource "vultr_vpc" "main" {
  count = local.create_vpc ? 1 : 0

  description = "${local.name_prefix}-vpc"
  region      = var.region_code
}

locals {
  vpc_id          = local.create_vpc ? vultr_vpc.main[0].id : var.existing_vpc_id
  vpc_cidr        = local.create_vpc ? "${vultr_vpc.main[0].v4_subnet}/${vultr_vpc.main[0].v4_subnet_mask}" : var.existing_vpc_cidr
  vpc_subnet      = split("/", local.vpc_cidr)[0]
  vpc_subnet_mask = tonumber(split("/", local.vpc_cidr)[1])

  db_cidrs = distinct(concat(
    [local.vpc_cidr],
    var.admin_ipv4_cidrs,
    var.db_access_ipv4_cidrs
  ))
}

resource "vultr_firewall_group" "db" {
  description = "${local.name_prefix}-db-fw"
}

resource "vultr_firewall_group" "web" {
  description = "${local.name_prefix}-web-fw"
}

resource "vultr_firewall_group" "analytics" {
  description = "${local.name_prefix}-analytics-fw"
}

resource "vultr_firewall_rule" "db_ssh" {
  for_each = local.admin_cidr_map

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "22"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "web_ssh" {
  for_each = local.admin_cidr_map

  firewall_group_id = vultr_firewall_group.web.id
  protocol          = "tcp"
  port              = "22"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "analytics_ssh" {
  for_each = var.global_analytics_client_enabled ? local.admin_cidr_map : {}

  firewall_group_id = vultr_firewall_group.analytics.id
  protocol          = "tcp"
  port              = "22"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "analytics_pgbouncer" {
  for_each = var.global_analytics_client_enabled ? local.admin_cidr_map : {}

  firewall_group_id = vultr_firewall_group.analytics.id
  protocol          = "tcp"
  port              = "6432"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "analytics_postgres_vpc" {
  count = var.global_analytics_client_enabled && var.web_portal_enabled ? 1 : 0

  firewall_group_id = vultr_firewall_group.analytics.id
  protocol          = "tcp"
  port              = "5432"
  ip_type           = "v4"
  subnet            = local.vpc_subnet
  subnet_size       = local.vpc_subnet_mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_postgres" {
  for_each = local.external_db_cidr_map

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "5432"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_pgbouncer" {
  for_each = local.external_db_cidr_map

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "6432"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_postgres_global_analytics_client" {
  count = var.global_analytics_client_enabled ? 1 : 0

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "5432"
  ip_type           = "v4"
  subnet            = local.global_analytics_client_public_ip
  subnet_size       = 32

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_pgbouncer_global_analytics_client" {
  count = var.global_analytics_client_enabled ? 1 : 0

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "6432"
  ip_type           = "v4"
  subnet            = local.global_analytics_client_public_ip
  subnet_size       = 32

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_postgres_global_analytics_client_ipv6" {
  count = var.global_analytics_client_enabled ? 1 : 0

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "5432"
  ip_type           = "v6"
  subnet            = cidrhost("${local.global_analytics_client_public_ipv6}/128", 0)
  subnet_size       = 128

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_pgbouncer_global_analytics_client_ipv6" {
  count = var.global_analytics_client_enabled ? 1 : 0

  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "6432"
  ip_type           = "v6"
  subnet            = cidrhost("${local.global_analytics_client_public_ipv6}/128", 0)
  subnet_size       = 128

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "web_http" {
  for_each = var.backend_count > 0 || var.web_portal_enabled ? local.web_cidr_map : {}

  firewall_group_id = vultr_firewall_group.web.id
  protocol          = "tcp"
  port              = "80"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "web_https" {
  for_each = var.backend_count > 0 || var.web_portal_enabled ? local.web_cidr_map : {}

  firewall_group_id = vultr_firewall_group.web.id
  protocol          = "tcp"
  port              = "443"
  ip_type           = "v4"
  subnet            = each.value.subnet
  subnet_size       = each.value.mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_instance" "worker" {
  count = local.use_instance_compute ? var.worker_count : 0

  region            = var.region_code
  plan              = var.worker_plan
  os_id             = var.os_id
  label             = "${local.name_prefix}-worker-${count.index + 1}"
  firewall_group_id = vultr_firewall_group.db.id
  enable_ipv6       = var.enable_ipv6
  activation_email  = false
  backups           = "disabled"
  ddos_protection   = false
  ssh_key_ids       = [for key in vultr_ssh_key.managed : key.id]
  vpc_ids           = [local.vpc_id]
  tags              = distinct(concat(local.all_tags, ["citus", "worker"]))

  user_data = templatefile("${path.module}/templates/citus-worker.yaml.tftpl", {
    postgres_version        = var.postgres_version
    citus_package           = var.citus_package
    postgres_admin_password = var.postgres_admin_password
    app_db_name             = var.app_db_name
    app_db_user             = var.app_db_user
    app_db_password         = var.app_db_password
    pg_hba_cidrs            = local.db_cidrs
  })
}

resource "vultr_bare_metal_server" "worker" {
  count = local.use_bare_metal_compute ? var.worker_count : 0

  region           = var.region_code
  plan             = var.worker_plan
  os_id            = var.os_id
  label            = "${local.name_prefix}-worker-${count.index + 1}"
  hostname         = "${local.name_prefix}-worker-${count.index + 1}"
  enable_ipv6      = var.enable_ipv6
  activation_email = false
  ssh_key_ids      = [for key in vultr_ssh_key.managed : key.id]
  vpc_id           = local.vpc_id
  mdisk_mode       = var.bare_metal_mdisk_mode
  tags             = distinct(concat(local.all_tags, ["citus", "worker", "bare-metal"]))

  user_data = templatefile("${path.module}/templates/citus-worker.yaml.tftpl", {
    postgres_version        = var.postgres_version
    citus_package           = var.citus_package
    postgres_admin_password = var.postgres_admin_password
    app_db_name             = var.app_db_name
    app_db_user             = var.app_db_user
    app_db_password         = var.app_db_password
    pg_hba_cidrs            = local.db_cidrs
  })
}

resource "vultr_instance" "coordinator" {
  count = local.use_instance_compute ? 1 : 0

  region            = var.region_code
  plan              = var.coordinator_plan
  os_id             = var.os_id
  label             = "${local.name_prefix}-coord"
  firewall_group_id = vultr_firewall_group.db.id
  enable_ipv6       = var.enable_ipv6
  activation_email  = false
  backups           = "disabled"
  ddos_protection   = false
  ssh_key_ids       = [for key in vultr_ssh_key.managed : key.id]
  vpc_ids           = [local.vpc_id]
  tags              = distinct(concat(local.all_tags, ["citus", "coordinator"]))

  user_data = templatefile("${path.module}/templates/citus-coordinator.yaml.tftpl", {
    postgres_version        = var.postgres_version
    citus_package           = var.citus_package
    postgres_admin_password = var.postgres_admin_password
    app_db_name             = var.app_db_name
    app_db_user             = var.app_db_user
    app_db_password         = var.app_db_password
    pg_hba_cidrs            = local.db_cidrs
    worker_private_ips      = local.worker_db_ips
  })
}

resource "vultr_bare_metal_server" "coordinator" {
  count = local.use_bare_metal_compute ? 1 : 0

  region           = var.region_code
  plan             = var.coordinator_plan
  os_id            = var.os_id
  label            = "${local.name_prefix}-coord"
  hostname         = "${local.name_prefix}-coord"
  enable_ipv6      = var.enable_ipv6
  activation_email = false
  ssh_key_ids      = [for key in vultr_ssh_key.managed : key.id]
  vpc_id           = local.vpc_id
  mdisk_mode       = var.bare_metal_mdisk_mode
  tags             = distinct(concat(local.all_tags, ["citus", "coordinator", "bare-metal"]))

  user_data = templatefile("${path.module}/templates/citus-coordinator.yaml.tftpl", {
    postgres_version        = var.postgres_version
    citus_package           = var.citus_package
    postgres_admin_password = var.postgres_admin_password
    app_db_name             = var.app_db_name
    app_db_user             = var.app_db_user
    app_db_password         = var.app_db_password
    pg_hba_cidrs            = local.db_cidrs
    worker_private_ips      = local.worker_db_ips
  })
}

resource "vultr_instance" "backend" {
  count = local.use_instance_compute ? var.backend_count : 0

  region            = var.region_code
  plan              = var.backend_plan
  os_id             = var.os_id
  label             = "${local.name_prefix}-api-${count.index + 1}"
  firewall_group_id = vultr_firewall_group.web.id
  enable_ipv6       = var.enable_ipv6
  activation_email  = false
  backups           = "disabled"
  ddos_protection   = false
  ssh_key_ids       = [for key in vultr_ssh_key.managed : key.id]
  vpc_ids           = [local.vpc_id]
  tags              = distinct(concat(local.all_tags, ["api"]))

  user_data = templatefile("${path.module}/templates/backend.yaml.tftpl", {
    app_port                  = var.app_port
    local_db_host             = local.coordinator_db_ip
    local_db_name             = var.app_db_name
    local_db_user             = var.app_db_user
    local_db_password         = var.app_db_password
    remote_analytics_base_url = var.remote_analytics_base_url
  })
}

resource "vultr_bare_metal_server" "backend" {
  count = local.use_bare_metal_compute ? var.backend_count : 0

  region           = var.region_code
  plan             = var.backend_plan
  os_id            = var.os_id
  label            = "${local.name_prefix}-api-${count.index + 1}"
  hostname         = "${local.name_prefix}-api-${count.index + 1}"
  enable_ipv6      = var.enable_ipv6
  activation_email = false
  ssh_key_ids      = [for key in vultr_ssh_key.managed : key.id]
  vpc_id           = local.vpc_id
  mdisk_mode       = var.bare_metal_mdisk_mode
  tags             = distinct(concat(local.all_tags, ["api", "bare-metal"]))

  user_data = templatefile("${path.module}/templates/backend.yaml.tftpl", {
    app_port                  = var.app_port
    local_db_host             = local.coordinator_db_ip
    local_db_name             = var.app_db_name
    local_db_user             = var.app_db_user
    local_db_password         = var.app_db_password
    remote_analytics_base_url = var.remote_analytics_base_url
  })
}

resource "vultr_instance" "web_portal" {
  count = var.web_portal_enabled ? 1 : 0

  region            = var.region_code
  plan              = var.web_portal_plan
  os_id             = var.os_id
  label             = "${local.name_prefix}-web-portal"
  firewall_group_id = vultr_firewall_group.web.id
  enable_ipv6       = var.enable_ipv6
  activation_email  = false
  backups           = "disabled"
  ddos_protection   = false
  ssh_key_ids       = [for key in vultr_ssh_key.managed : key.id]
  vpc_ids           = [local.vpc_id]
  tags              = distinct(concat(local.all_tags, ["web-portal", "pgweb", "viewer"]))

  user_data = templatefile("${path.module}/templates/web-portal.yaml.tftpl", {})
}

resource "vultr_instance" "global_analytics_client" {
  count = var.global_analytics_client_enabled && local.use_instance_analytics ? 1 : 0

  region            = local.global_analytics_client_region_code
  plan              = var.global_analytics_client_plan
  os_id             = var.os_id
  label             = "${local.name_prefix}-global-analytics-client"
  firewall_group_id = vultr_firewall_group.analytics.id
  enable_ipv6       = var.enable_ipv6
  activation_email  = false
  backups           = "disabled"
  ddos_protection   = false
  ssh_key_ids       = [for key in vultr_ssh_key.managed : key.id]
  vpc_ids           = var.global_analytics_client_attach_vpc ? [local.vpc_id] : []
  tags              = distinct(concat(local.all_tags, ["analytics", "global-client"]))

  user_data = templatefile("${path.module}/templates/global-analytics-client.yaml.tftpl", {})
}

resource "vultr_bare_metal_server" "global_analytics_client" {
  count = var.global_analytics_client_enabled && local.use_bare_metal_analytics ? 1 : 0

  region           = local.global_analytics_client_region_code
  plan             = var.global_analytics_client_plan
  os_id            = var.os_id
  label            = "${local.name_prefix}-global-analytics-client"
  hostname         = "${local.name_prefix}-global-analytics-client"
  enable_ipv6      = var.enable_ipv6
  activation_email = false
  ssh_key_ids      = [for key in vultr_ssh_key.managed : key.id]
  vpc_id           = var.global_analytics_client_attach_vpc ? local.vpc_id : null
  mdisk_mode       = var.bare_metal_mdisk_mode
  tags             = distinct(concat(local.all_tags, ["analytics", "global-client", "bare-metal"]))

  user_data = templatefile("${path.module}/templates/global-analytics-client.yaml.tftpl", {})
}

resource "vultr_firewall_rule" "db_postgres_vpc" {
  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "5432"
  ip_type           = "v4"
  subnet            = local.vpc_subnet
  subnet_size       = local.vpc_subnet_mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_firewall_rule" "db_pgbouncer_vpc" {
  firewall_group_id = vultr_firewall_group.db.id
  protocol          = "tcp"
  port              = "6432"
  ip_type           = "v4"
  subnet            = local.vpc_subnet
  subnet_size       = local.vpc_subnet_mask

  lifecycle {
    ignore_changes = [source]
  }
}

resource "vultr_load_balancer" "web" {
  count               = local.use_instance_compute && var.backend_count > 0 ? 1 : 0
  region              = var.region_code
  label               = "${local.name_prefix}-lb"
  balancing_algorithm = "roundrobin"
  attached_instances  = [for backend in vultr_instance.backend : backend.id]
  vpc                 = local.vpc_id

  forwarding_rules {
    frontend_protocol = "http"
    frontend_port     = 80
    backend_protocol  = "http"
    backend_port      = var.app_port
  }

  health_check {
    protocol            = "http"
    path                = "/healthz"
    port                = var.app_port
    check_interval      = 10
    response_timeout    = 5
    unhealthy_threshold = 3
    healthy_threshold   = 2
  }
}
