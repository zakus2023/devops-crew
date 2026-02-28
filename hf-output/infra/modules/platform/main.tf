# Platform module for ${var.project}-${var.env}
# Placeholder: crew-DevOps/infra/modules/platform not found. Add full platform .tf files there and re-run to copy.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
    null = { source = "hashicorp/null", version = ">= 3.0" }
  }
}

resource "aws_ssm_parameter" "image_tag" {
  name  = "/${var.project}/${var.env}/image_tag"
  type  = "String"
  value = "initial"
}

resource "aws_ssm_parameter" "ecr_repo_name" {
  name  = "/${var.project}/${var.env}/ecr_repo_name"
  type  = "String"
  value = "${var.project}-${var.env}-app"
}
