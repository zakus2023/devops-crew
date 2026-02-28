output "https_url" { value = module.platform.https_url }
output "artifacts_bucket" { value = module.platform.artifacts_bucket }
output "ecr_repo" { value = module.platform.ecr_repo }
output "codedeploy_app" { value = module.platform.codedeploy_app }
output "codedeploy_group" { value = module.platform.codedeploy_group }
output "bastion_public_ip" { value = module.platform.bastion_public_ip }
output "ecs_cluster_name" { value = module.platform.ecs_cluster_name }
output "ecs_service_name" { value = module.platform.ecs_service_name }
