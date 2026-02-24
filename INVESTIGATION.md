# Investigation: Health Check Failed / Overall Fail

## Summary

Pipeline ran **Generate → Infra → Build → Deploy → Verify**. Result:
- **Health check:** failed (connection error, DNS resolution)
- **SSM image_tag:** latest ✓
- **SSM ecr_repo_name:** bluegreen-prod-app ✓
- **Overall:** fail

## Root Cause Chain

### 1. Terraform apply failed (dev and prod)

Agent output: *"Dev and Prod apply failed with VpcLimitExceeded and AddressLimitExceeded."*

**Dependency chain:** VPC → EIP (NAT) → subnets → ALB → target groups → ECS service (or ASG). When VPC or EIP creation fails, nothing downstream is created.

Consequences:
- **No VPC / no NAT** → No subnets, ALB, target groups
- **No ECS service, no EC2/ASG** → Deploy fails
- **No ALB, no Route53 app record** → Health check fails (DNS resolution error for `app.my-iifb.click`)
- Build succeeded because ECR and SSM params are created early before the VPC/NAT resources.

### 2. Deploy method vs Terraform mismatch

- **Combined-Crew/.env:** `DEPLOY_METHOD=ecs`
- **Multi-Agent-Pipeline/.env:** `DEPLOY_METHOD=ssh_script`
- **test-ui/output prod.tfvars:** `enable_ecs=false` (EC2/CodeDeploy)

When using the UI, deploy method comes from the UI selection. If `ssh_script` is selected but Terraform never completed, no EC2 instances exist. If `ecs` is selected but `enable_ecs=false` in tfvars, ECS deploy fails (no cluster/service).

**Rule:** `DEPLOY_METHOD` must match `enable_ecs` in generated tfvars:
- `ssh_script` → `enable_ecs=false` (EC2)
- `ecs` → `enable_ecs=true` (ECS)

### 3. DNS / health check failure

`app.my-iifb.click` fails to resolve. Possible causes:

1. **Route53 A record not created** – Terraform did not reach the `aws_route53_record.app_alias` resource (depends on ALB).
2. **Domain delegation** – `my-iifb.click` must have nameservers at the registrar pointing to the Route53 hosted zone `Z04241223G31RGIMMIL2C`. Otherwise, `app.my-iifb.click` will not resolve publicly.
3. **Partial Terraform apply** – ALB or Route53 resources may not have been created if the apply failed midway.

## Files Checked

| File | Finding |
|------|---------|
| **Combined-Crew/.env** | DEPLOY_METHOD=ecs, PROD_URL=https://app.my-iifb.click, ALLOW_TERRAFORM_APPLY=1 |
| **Multi-Agent-Pipeline/.env** | DEPLOY_METHOD=ssh_script, REPO_ROOT points to Full-Orchestrator/output (different from test-ui/output) |
| **Full-Orchestrator/.env** | DEPLOY_METHOD=ecs, ALLOW_TERRAFORM_APPLY=1 |
| **test-ui/output/infra/envs/prod/prod.tfvars** | enable_ecs=false, enable_bastion=true, domain_name=app.my-iifb.click |
| **test-ui/output/infra/envs/prod/outputs.tf** | https_url = "https://app.my-iifb.click" (from platform module) |

## Fixes Applied

1. **UI defaults from .env** – `deploy_method`, `allow_terraform_apply`, and `prod_url` in the Gradio UI now default from `.env`.
2. **Verify task hint** – When health check fails with DNS/connection error, the verify instruction now mentions Terraform completion and domain delegation.
3. **Multi-Agent-Pipeline .env** – Added comment that `DEPLOY_METHOD` must match `enable_ecs` in the generated project.

## Recommended Next Steps

1. **Resolve AWS VPC/EIP limits** (dev+prod need 2 VPCs, 2 EIPs; default limit 5 each)
   ```bash
   python Combined-Crew/scripts/resolve-aws-limits.py --region us-east-1
   python Combined-Crew/scripts/resolve-aws-limits.py --release-unassociated-eips --region us-east-1
   ```
   Delete unused VPCs in AWS Console if you have 5+.
2. **Resolve Terraform blockers**
   ```bash
   python Combined-Crew/scripts/remove-terraform-blockers.py --region us-east-1
   python Combined-Crew/scripts/remove-cloudwatch-logs.py --region us-east-1
   ```
3. **Re-run Terraform apply** for dev and prod with `ALLOW_TERRAFORM_APPLY=1`.
3. **Verify domain delegation** – Ensure `my-iifb.click` NS records at the registrar point to the Route53 hosted zone.
4. **Choose deploy method** – Either:
   - `DEPLOY_METHOD=ssh_script` with `enable_ecs=false` (EC2), or
   - `DEPLOY_METHOD=ecs` with `enable_ecs=true` (ECS) in requirements, then re-generate and re-apply.
5. **Re-run the pipeline** once Terraform succeeds and EC2/ECS instances are available.
