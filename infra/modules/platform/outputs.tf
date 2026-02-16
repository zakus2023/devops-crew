output "alb_dns_name"   { value = aws_lb.app.dns_name }
output "app_domain"     { value = var.domain_name }
output "https_url"      { value = "https://${var.domain_name}" }
output "ecr_repo"       { value = aws_ecr_repository.app.name }
output "codedeploy_app" {
  value       = var.enable_ecs ? null : aws_codedeploy_app.app[0].name
  description = "CodeDeploy app name (null when enable_ecs=true)."
}
output "codedeploy_group" {
  value       = var.enable_ecs ? null : aws_codedeploy_deployment_group.dg[0].deployment_group_name
  description = "CodeDeploy deployment group (null when enable_ecs=true)."
}
output "artifacts_bucket" {
  value       = var.enable_ecs ? null : aws_s3_bucket.artifacts[0].bucket
  description = "CodeDeploy/Ansible artifacts bucket (null when enable_ecs=true)."
}
output "bastion_public_ip" {
  value       = var.enable_bastion && !var.enable_ecs && var.key_name != "" ? aws_instance.bastion[0].public_ip : null
  description = "Bastion public IP for SSH ProxyJump when using EC2 deploy; set BASTION_HOST in .env. Null when enable_ecs=true."
}

output "ecs_cluster_name" {
  value       = var.enable_ecs ? aws_ecs_cluster.app[0].name : null
  description = "ECS cluster name for DEPLOY_METHOD=ecs (pipeline run_ecs_deploy)."
}

output "ecs_service_name" {
  value       = var.enable_ecs ? aws_ecs_service.app[0].name : null
  description = "ECS service name for DEPLOY_METHOD=ecs (pipeline run_ecs_deploy)."
}