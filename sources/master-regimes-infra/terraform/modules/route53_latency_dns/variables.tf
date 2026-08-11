variable "zone_id" {
  description = "Route53 hosted zone identifier."
  type        = string
}

variable "root_domain" {
  description = "Base domain, for example example.com."
  type        = string
}

variable "record_name" {
  description = "Subdomain name placed in front of root_domain."
  type        = string
  default     = "api"
}

variable "eu_lb_ip" {
  description = "IPv4 address of the EU load balancer."
  type        = string
}

variable "us_lb_ip" {
  description = "IPv4 address of the US load balancer."
  type        = string
}

variable "eu_latency_region" {
  description = "AWS latency routing label for Europe."
  type        = string
  default     = "eu-west-1"
}

variable "us_latency_region" {
  description = "AWS latency routing label for the United States."
  type        = string
  default     = "us-east-1"
}

variable "ttl" {
  description = "DNS TTL in seconds."
  type        = number
  default     = 30
}

