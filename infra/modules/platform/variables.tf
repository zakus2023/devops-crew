variable "project" { type = string }
variable "region"  { type = string }
variable "env"     { type = string } # "dev" or "prod"

variable "domain_name"    { type = string }
variable "hosted_zone_id" { type = string }
variable "alarm_email"   { type = string }

variable "vpc_cidr"        { type = string }
variable "public_subnets"  { type = list(string) }
variable "private_subnets" { type = list(string) }

variable "instance_type"    { type = string }
variable "min_size"         { type = number }
variable "max_size"         { type = number }
variable "desired_capacity" { type = number }

variable "ami_id" {
  type    = string
  default = ""
}

variable "cloudtrail_bucket" { type = string }

variable "enable_guardduty" {
  type    = bool
  default = true
}

variable "enable_securityhub" {
  type    = bool
  default = true
}

variable "enable_inspector2" {
  type    = bool
  default = true
}

variable "enable_config" {
  type    = bool
  default = true
}

variable "enable_deployment_alarms" {
  type    = bool
  default = true
}