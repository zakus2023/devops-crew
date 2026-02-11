output "alb_dns_name"     { value = aws_lb.app.dns_name }
output "app_domain"       { value = var.domain_name }
output "https_url"        { value = "https://${var.domain_name}" }
output "ecr_repo"         { value = aws_ecr_repository.app.name }
output "codedeploy_app"   { value = aws_codedeploy_app.app.name }
output "codedeploy_group" { value = aws_codedeploy_deployment_group.dg.deployment_group_name }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }