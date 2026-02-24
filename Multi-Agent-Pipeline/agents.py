"""
Multi-Agent Deploy Pipeline: four specialist agents.
- Infra Engineer: Terraform init, plan, apply (bootstrap, dev, prod).
- Build Engineer: Docker build, ECR push, SSM image_tag update.
- Deploy Engineer: Ansible, SSH script, or ECS (per DEPLOY_METHOD).
- Verifier: HTTP health check and SSM read to confirm deployment.
"""
from crewai import Agent

from tools import (
    terraform_init,
    terraform_plan,
    terraform_apply,
    update_backend_from_bootstrap,
    run_resolve_aws_limits,
    run_remove_terraform_blockers,
    run_import_platform_iam_on_conflict,
    docker_build,
    ecr_push_and_ssm,
    read_ssm_parameter,
    get_terraform_output,
    run_ansible_deploy,
    run_ssh_deploy,
    run_ecs_deploy,
    wait_seconds,
    http_health_check,
)


infra_engineer = Agent(
    role="Infrastructure Engineer",
    goal="Run Terraform init, plan, and (if allowed) apply for bootstrap, dev, and prod so infrastructure is ready for the app.",
    backstory="You are a careful infrastructure engineer. Before dev/prod apply, call run_resolve_aws_limits(region, release_eips=True) and run_remove_terraform_blockers(region) to free VPC/EIP quota and remove CloudTrail conflicts. You run terraform init with the correct backend config, then terraform plan, then terraform apply only when ALLOW_TERRAFORM_APPLY=1. After a successful bootstrap apply, call update_backend_from_bootstrap(). If apply fails with VpcLimitExceeded, AddressLimitExceeded, or ResourceAlreadyExistsException, run cleanup and retry. If apply fails with EntityAlreadyExists for IAM Role, call run_import_platform_iam_on_conflict(relative_path, var_file) to import existing ec2_role and codedeploy_role into state, then retry terraform_apply.",
    tools=[terraform_init, terraform_plan, terraform_apply, update_backend_from_bootstrap, run_resolve_aws_limits, run_remove_terraform_blockers, run_import_platform_iam_on_conflict],
    verbose=True,
    allow_delegation=False,
)

build_engineer = Agent(
    role="Build Engineer",
    goal="Build the Docker image for the app, push it to ECR, and update the SSM parameter /bluegreen/prod/image_tag so the deploy step can use the new image.",
    backstory="You are a CI/CD build engineer. You run docker build for the app directory, then push the image to ECR. Get ECR repo name from read_ssm_parameter('/bluegreen/prod/ecr_repo_name'); if ParameterNotFound, try get_terraform_output('ecr_repo', 'infra/envs/prod'). Update /bluegreen/prod/image_tag so deployment uses the new tag.",
    tools=[docker_build, ecr_push_and_ssm, read_ssm_parameter, get_terraform_output],
    verbose=True,
    allow_delegation=False,
)

deploy_engineer = Agent(
    role="Deployment Engineer",
    goal="Trigger the deployment so the new image runs in production. Use the tool that matches DEPLOY_METHOD: ansible (run_ansible_deploy), ssh_script (run_ssh_deploy), or ecs (run_ecs_deploy). If unset, prefer ansible when artifacts_bucket is available, else describe options.",
    backstory="You are a deployment engineer. You support three deploy methods: (1) Ansible — run_ansible_deploy with env and ssm_bucket; get ssm_bucket via get_terraform_output('artifacts_bucket', 'infra/envs/prod'). (2) SSH script — run_ssh_deploy(env='prod', region=...) when DEPLOY_METHOD=ssh_script; requires SSH key (SSH_KEY_PATH or SSH_PRIVATE_KEY) and EC2 instances tagged Env=prod reachable on port 22. (3) ECS — run_ecs_deploy(cluster_name, service_name, region=...) when DEPLOY_METHOD=ecs; get cluster and service names from get_terraform_output('ecs_cluster_name', 'infra/envs/prod') and get_terraform_output('ecs_service_name', 'infra/envs/prod') or from SSM/context. Do not ask the user for confirmation when you can get values from tools.",
    tools=[get_terraform_output, run_ansible_deploy, run_ssh_deploy, run_ecs_deploy, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

verifier_agent = Agent(
    role="Deployment Verifier",
    goal="Verify that the production HTTPS health endpoint returns 200 and that SSM parameters /bluegreen/prod/image_tag and /bluegreen/prod/ecr_repo_name are set correctly.",
    backstory="You are a careful DevOps verifier. Prefer the prod URL from get_terraform_output('https_url', 'infra/envs/prod') so it matches Terraform (e.g. https://app.example.com, no www). Fall back to PROD_URL only if Terraform output is unavailable. Then use http_health_check and read_ssm_parameter.",
    tools=[wait_seconds, http_health_check, read_ssm_parameter, get_terraform_output],
    verbose=True,
    allow_delegation=False,
)
