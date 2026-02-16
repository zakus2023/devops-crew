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

# ECS cluster/service names for pipeline DEPLOY_METHOD=ecs (fallback when Terraform output not available)
resource "aws_ssm_parameter" "ecs_cluster_name" {
  count     = var.enable_ecs ? 1 : 0
  name      = "/bluegreen/${var.env}/ecs_cluster_name"
  type      = "String"
  value     = aws_ecs_cluster.app[0].name
  overwrite = true
}

resource "aws_ssm_parameter" "ecs_service_name" {
  count     = var.enable_ecs ? 1 : 0
  name      = "/bluegreen/${var.env}/ecs_service_name"
  type      = "String"
  value     = aws_ecs_service.app[0].name
  overwrite = true
}