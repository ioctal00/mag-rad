variable "vultr_api_key" {
  description = "Optional Vultr API key. Leave empty to use VULTR_API_KEY."
  type        = string
  sensitive   = true
  default     = ""
}

variable "project_tag" {
  description = "Short project slug."
  type        = string
  default     = "sivbp"
}

variable "region_code" {
  description = "Vultr region code for the logical APAC deployment."
  type        = string
  default     = "ams"
}

variable "existing_vpc_id" {
  description = "Existing anchor VPC ID for shared-VPC logical APAC runs."
  type        = string
  default     = ""
}

variable "existing_vpc_cidr" {
  description = "CIDR of the anchor VPC used by the logical APAC stack."
  type        = string
  default     = ""
}

variable "ssh_keys" {
  description = "Map of SSH key name to public key contents."
  type        = map(string)
}

variable "admin_ipv4_cidrs" {
  description = "IPv4 CIDRs allowed to SSH and connect to PostgreSQL."
  type        = list(string)
}

variable "web_ipv4_cidrs" {
  description = "IPv4 CIDRs allowed to access the load-balanced web service."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "db_access_ipv4_cidrs" {
  description = "Additional IPv4 CIDRs allowed to access PostgreSQL."
  type        = list(string)
  default     = []
}

variable "backend_count" {
  type    = number
  default = 0
}

variable "worker_count" {
  type    = number
  default = 0
}

variable "compute_resource_type" {
  type    = string
  default = "bare_metal"
}

variable "backend_plan" {
  type    = string
  default = "vbm-6c-32gb"
}

variable "web_portal_enabled" {
  type    = bool
  default = false
}

variable "web_portal_plan" {
  type    = string
  default = "vhf-1c-2gb"
}

variable "coordinator_plan" {
  type    = string
  default = "vbm-6c-32gb"
}

variable "worker_plan" {
  type    = string
  default = "vbm-6c-32gb"
}

variable "bare_metal_mdisk_mode" {
  type    = string
  default = null
}

variable "os_id" {
  type    = number
  default = 1743
}

variable "enable_ipv6" {
  type    = bool
  default = true
}

variable "app_port" {
  type    = number
  default = 8000
}

variable "postgres_version" {
  type    = string
  default = "18"
}

variable "citus_package" {
  type    = string
  default = "postgresql-18-citus-14.0"
}

variable "postgres_admin_password" {
  type      = string
  sensitive = true
}

variable "app_db_name" {
  type    = string
  default = "app"
}

variable "app_db_user" {
  type    = string
  default = "app"
}

variable "app_db_password" {
  type      = string
  sensitive = true
}

variable "remote_analytics_base_url" {
  type    = string
  default = ""
}

variable "tags" {
  type    = list(string)
  default = []
}
