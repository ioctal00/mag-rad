variable "project_tag" {
  description = "Short project slug used in resource names and tags."
  type        = string
}

variable "environment" {
  description = "Environment name, for example eu or us."
  type        = string
}

variable "region_code" {
  description = "Vultr region code, for example ams or ewr."
  type        = string
}

variable "existing_vpc_id" {
  description = "Optional existing Vultr VPC ID. When set, this module attaches compute to that VPC instead of creating a new one."
  type        = string
  default     = ""
}

variable "existing_vpc_cidr" {
  description = "IPv4 CIDR for existing_vpc_id, for example 10.1.96.0/20. Required when existing_vpc_id is set."
  type        = string
  default     = ""
}

variable "ssh_keys" {
  description = "Map of SSH key name to public key contents."
  type        = map(string)
}

variable "admin_ipv4_cidrs" {
  description = "IPv4 CIDRs that may SSH into instances and connect to PostgreSQL directly."
  type        = list(string)
  default     = []
}

variable "web_ipv4_cidrs" {
  description = "IPv4 CIDRs allowed to access backend HTTP and HTTPS."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "db_access_ipv4_cidrs" {
  description = "Additional IPv4 CIDRs allowed to connect to PostgreSQL, useful for future FDW or remote runners."
  type        = list(string)
  default     = []
}

variable "backend_count" {
  description = "Number of backend servers behind the regional load balancer."
  type        = number
  default     = 2
}

variable "worker_count" {
  description = "Number of Citus worker nodes."
  type        = number
  default     = 3
}

variable "compute_resource_type" {
  description = "Compute resource type for Citus nodes: instance for cloud VPS, bare_metal for Vultr Bare Metal."
  type        = string
  default     = "instance"

  validation {
    condition     = contains(["instance", "bare_metal"], var.compute_resource_type)
    error_message = "compute_resource_type must be either instance or bare_metal."
  }
}

variable "backend_plan" {
  description = "Vultr plan slug for backend instances."
  type        = string
  default     = "vc2-2c-4gb"
}

variable "global_analytics_client_enabled" {
  description = "Whether to create one global analytics client server."
  type        = bool
  default     = false
}

variable "global_analytics_client_region_code" {
  description = "Vultr region code for the global analytics client. Keep equal to region_code when attaching it to the regional VPC."
  type        = string
  default     = ""
}

variable "global_analytics_client_plan" {
  description = "Vultr plan slug for the global analytics client."
  type        = string
  default     = "vc2-1c-1gb"
}

variable "global_analytics_client_resource_type" {
  description = "Compute resource type for the optional global analytics client. Empty means use compute_resource_type."
  type        = string
  default     = ""

  validation {
    condition     = var.global_analytics_client_resource_type == "" || contains(["instance", "bare_metal"], var.global_analytics_client_resource_type)
    error_message = "global_analytics_client_resource_type must be empty, instance, or bare_metal."
  }
}

variable "bare_metal_mdisk_mode" {
  description = "Optional Vultr Bare Metal disk mode. Leave null to use Vultr/provider default for the selected plan."
  type        = string
  default     = null
}

variable "global_analytics_client_attach_vpc" {
  description = "Whether to attach the global analytics client to the regional VPC. Keep false when the analytics node should model an external/global client even if it runs in the same Vultr region."
  type        = bool
  default     = false
}

variable "web_portal_enabled" {
  description = "Whether to create a small public web portal host for Pgweb and the regime diagnosis viewer."
  type        = bool
  default     = false
}

variable "web_portal_plan" {
  description = "Small Vultr VPS plan slug for the web portal host."
  type        = string
  default     = "vhf-1c-2gb"
}

variable "coordinator_plan" {
  description = "Vultr plan slug for the Citus coordinator."
  type        = string
  default     = "vc2-2c-4gb"
}

variable "worker_plan" {
  description = "Vultr plan slug for Citus worker instances."
  type        = string
  default     = "vc2-2c-4gb"
}

variable "os_id" {
  description = "Vultr OS identifier for the base image."
  type        = number
  default     = 1743
}

variable "enable_ipv6" {
  description = "Whether to enable IPv6 on instances."
  type        = bool
  default     = true
}

variable "app_port" {
  description = "Backend application listen port."
  type        = number
  default     = 8000
}

variable "postgres_version" {
  description = "PostgreSQL major version used in package names and configuration paths."
  type        = string
  default     = "16"
}

variable "citus_package" {
  description = "Exact apt package name for the Citus extension."
  type        = string
  default     = "postgresql-18-citus-14.0"
}

variable "postgres_admin_password" {
  description = "Password assigned to the postgres superuser."
  type        = string
  sensitive   = true
  default     = ""
}

variable "app_db_name" {
  description = "Application database name exposed through the coordinator."
  type        = string
  default     = "app"
}

variable "app_db_user" {
  description = "Application database user."
  type        = string
  default     = "app"
}

variable "app_db_password" {
  description = "Password for the application database user."
  type        = string
  sensitive   = true
  default     = ""
}

variable "remote_analytics_base_url" {
  description = "Optional remote regional API base URL, used later by manually decomposed live-federation clients."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Additional Vultr tags."
  type        = list(string)
  default     = []
}
