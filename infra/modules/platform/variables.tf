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

# Create CloudTrail trail. Disable in dev to avoid conflicts (only one env creates trail).
variable "enable_cloudtrail" {
  type    = bool
  default = true
}

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

# Optional bastion host for SSH deploy (DEPLOY_METHOD=ssh_script) from your machine to private instances.
variable "enable_bastion" {
  type    = bool
  default = false
}

# Key pair name for bastion and app instances (required if enable_bastion = true; recommended for ssh_script deploy).
variable "key_name" {
  type    = string
  default = ""
}

# CIDR allowed to SSH to the bastion (e.g. "0.0.0.0/0" or your office IP/32).
variable "allowed_bastion_cidr" {
  type    = string
  default = "0.0.0.0/0"
}

# Optional ECS (Fargate) deploy target. When true, creates cluster, service, task definition, and ALB listener rule.
# Pipeline DEPLOY_METHOD=ecs uses ecs_cluster_name and ecs_service_name (from Terraform outputs or SSM).
variable "enable_ecs" {
  type    = bool
  default = false
}

# CodeDeploy is not used; pipeline uses ssh_script, ansible (SSM), or ecs. When false, no CodeDeploy app/role/group or agent install.
variable "enable_codedeploy" {
  type    = bool
  default = false
}