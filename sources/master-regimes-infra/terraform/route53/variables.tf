variable "aws_region" {
  description = "AWS provider region used for Route53 operations."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Optional AWS profile name."
  type        = string
  default     = ""
}

variable "create_api_record" {
  description = "Whether to create the latency-based API record."
  type        = bool
  default     = true
}

variable "zone_id" {
  description = "Route53 hosted zone identifier."
  type        = string
}

variable "root_domain" {
  description = "Base domain, for example example.com."
  type        = string
}

variable "record_name" {
  description = "Subdomain used for the latency-routed API."
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

variable "ttl" {
  description = "DNS TTL in seconds."
  type        = number
  default     = 30
}

variable "eu_latency_region" {
  description = "AWS latency routing label for the EU endpoint."
  type        = string
  default     = "eu-west-1"
}

variable "us_latency_region" {
  description = "AWS latency routing label for the US endpoint."
  type        = string
  default     = "us-east-1"
}

