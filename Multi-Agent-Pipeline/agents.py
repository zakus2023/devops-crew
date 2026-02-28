"""
Multi-Agent Deploy Pipeline: four specialist agents.
- Infra Engineer: Terraform init, plan, apply (bootstrap, dev, prod).
- Build Engineer: Docker build, ECR push, SSM image_tag update.
- Deploy Engineer: Ansible, SSH script, or ECS (per DEPLOY_METHOD).
- Verifier: HTTP health check and SSM read to confirm deployment.
"""
from crewai import Agent

from tools import (
    run_full_infra_pipeline,
    docker_build,
    ecr_push_and_ssm,
    codebuild_build_and_push,
    read_pre_built_image_tag,
    write_ssm_image_tag,
    ecr_list_image_tags,
    read_ssm_parameter,
    read_ssm_image_tag,
    read_ssm_ecr_repo_name,
    get_terraform_output,
    run_ansible_deploy,
    run_ssh_deploy,
    run_ecs_deploy,
    wait_seconds,
    http_health_check,
)


infra_engineer = Agent(
    role="Infrastructure Engineer",
    goal="Run the full Terraform pipeline so infrastructure is ready for the app.",
    backstory="You run run_full_infra_pipeline(region) — the only tool you have. It does everything: resolve limits, remove blockers, bootstrap init/plan/apply, update_backend_from_bootstrap, dev init/plan/apply, prod init/plan/apply. Call it with the AWS region (e.g. us-east-1). Report the result.",
    tools=[run_full_infra_pipeline],
    verbose=True,
    allow_delegation=False,
)

build_engineer = Agent(
    role="Build Engineer",
    goal="Build the Docker image for the app, push it to ECR, and update the SSM parameter image_tag so the deploy step can use the new image.",
    backstory="You are a CI/CD build engineer. You run docker build for the app directory, then push the image to ECR. Get ECR repo name from read_ssm_ecr_repo_name(region); if ParameterNotFound, try get_terraform_output('ecr_repo', 'infra/envs/prod'). Use ecr_push_and_ssm to push and update image_tag. When Docker is unavailable (e.g. Hugging Face Space): call codebuild_build_and_push(ecr_repo_name, app_relative_path='app', region=...) to build automatically on AWS CodeBuild. If CodeBuild fails or is unavailable, fall back to read_pre_built_image_tag or ecr_list_image_tags; if a tag exists, call write_ssm_image_tag so deploy can proceed.",
    tools=[docker_build, ecr_push_and_ssm, codebuild_build_and_push, read_pre_built_image_tag, write_ssm_image_tag, ecr_list_image_tags, read_ssm_parameter, read_ssm_ecr_repo_name, get_terraform_output],
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
    goal="Verify that the production HTTPS health endpoint returns 200 and that SSM parameters image_tag and ecr_repo_name are set correctly.",
    backstory="You are a careful DevOps verifier. Prefer the prod URL from get_terraform_output('https_url', 'infra/envs/prod') so it matches Terraform (e.g. https://app.example.com, no www). Fall back to PROD_URL only if Terraform output is unavailable. Use read_ssm_image_tag(region) and read_ssm_ecr_repo_name(region) for SSM — do NOT use read_ssm_parameter with hand-constructed paths.",
    tools=[wait_seconds, http_health_check, read_ssm_image_tag, read_ssm_ecr_repo_name, get_terraform_output],
    verbose=True,
    allow_delegation=False,
)
