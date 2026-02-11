resource "aws_ssm_parameter" "ecr_repo_name" {
  name      = "/bluegreen/${var.env}/ecr_repo_name"
  type      = "String"
  value     = aws_ecr_repository.app.name
  overwrite = true
}

resource "aws_ssm_parameter" "image_tag" {
  name      = "/bluegreen/${var.env}/image_tag"
  type      = "String"
  value     = "unset"
  overwrite = true
}