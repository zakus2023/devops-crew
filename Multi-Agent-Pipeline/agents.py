"""
Multi-Agent Deploy Pipeline: four specialist agents.
- Infra Engineer: Terraform init, plan, apply (bootstrap, dev, prod).
- Build Engineer: Docker build, ECR push, SSM image_tag update.
- Deploy Engineer: CodeDeploy, Ansible, SSH script, or ECS (per DEPLOY_METHOD).
- Verifier: HTTP health check and SSM read to confirm deployment.
"""
from crewai import Agent

from tools import (
    terraform_init,
    terraform_plan,
    terraform_apply,
    update_backend_from_bootstrap,
    docker_build,
    ecr_push_and_ssm,
    read_ssm_parameter,
    get_terraform_output,
    trigger_codedeploy,
    run_ansible_deploy,
    run_ssh_deploy,
    run_ecs_deploy,
    wait_seconds,
    http_health_check,
)


infra_engineer = Agent(
    role="Infrastructure Engineer",
    goal="Run Terraform init, plan, and (if allowed) apply for bootstrap, dev, and prod so infrastructure is ready for the app.",
    backstory="You are a careful infrastructure engineer. You run terraform init with the correct backend config for each environment, then terraform plan to show changes, and terraform apply only when ALLOW_TERRAFORM_APPLY=1 is set. After a successful bootstrap apply, you call update_backend_from_bootstrap() so dev and prod get the real S3 bucket and DynamoDB table in backend.hcl and cloudtrail_bucket in tfvars. You work in the repo's infra/bootstrap, infra/envs/dev, infra/envs/prod.",
    tools=[terraform_init, terraform_plan, terraform_apply, update_backend_from_bootstrap],
    verbose=True,
    allow_delegation=False,
)

build_engineer = Agent(
    role="Build Engineer",
    goal="Build the Docker image for the app, push it to ECR, and update the SSM parameter /bluegreen/prod/image_tag so the deploy step can use the new image.",
    backstory="You are a CI/CD build engineer. You run docker build for the app directory, then push the image to ECR using the repo name from SSM or config, and update /bluegreen/prod/image_tag so deployment uses the new tag.",
    tools=[docker_build, ecr_push_and_ssm, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

deploy_engineer = Agent(
    role="Deployment Engineer",
    goal="Trigger the deployment so the new image runs in production. Use the tool that matches DEPLOY_METHOD: codedeploy (trigger_codedeploy), ansible (run_ansible_deploy), ssh_script (run_ssh_deploy), or ecs (run_ecs_deploy). If unset, prefer ansible when artifacts_bucket is available, else describe options.",
    backstory="You are a deployment engineer. You support four deploy methods: (1) CodeDeploy — trigger_codedeploy with application name, deployment group, s3_bucket and s3_key. (2) Ansible — run_ansible_deploy with env and ssm_bucket; get ssm_bucket via get_terraform_output('artifacts_bucket', 'infra/envs/prod'). (3) SSH script — run_ssh_deploy(env='prod', region=...) when DEPLOY_METHOD=ssh_script; requires SSH key (SSH_KEY_PATH or SSH_PRIVATE_KEY) and EC2 instances tagged Env=prod reachable on port 22. (4) ECS — run_ecs_deploy(cluster_name, service_name, region=...) when DEPLOY_METHOD=ecs; get cluster and service names from get_terraform_output('ecs_cluster_name', 'infra/envs/prod') and get_terraform_output('ecs_service_name', 'infra/envs/prod') or from SSM/context. Do not ask the user for confirmation when you can get values from tools.",
    tools=[get_terraform_output, trigger_codedeploy, run_ansible_deploy, run_ssh_deploy, run_ecs_deploy, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

verifier_agent = Agent(
    role="Deployment Verifier",
    goal="Verify that the production HTTPS health endpoint returns 200 and that SSM parameters /bluegreen/prod/image_tag and /bluegreen/prod/ecr_repo_name are set correctly.",
    backstory="You are a careful DevOps verifier. You use the HTTP health check and SSM read tools to confirm the deployment is live and configured.",
    tools=[wait_seconds, http_health_check, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)
