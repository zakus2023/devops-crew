"""
Multi-Agent Deploy Pipeline: four specialist agents.
- Infra Engineer: Terraform init, plan, apply (bootstrap, dev, prod).
- Build Engineer: Docker build, ECR push, SSM image_tag update.
- Deploy Engineer: Trigger CodeDeploy (or report deploy steps).
- Verifier: HTTP health check and SSM read to confirm deployment.
"""
from crewai import Agent

from tools import (
    terraform_init,
    terraform_plan,
    terraform_apply,
    docker_build,
    ecr_push_and_ssm,
    read_ssm_parameter,
    trigger_codedeploy,
    run_ansible_deploy,
    http_health_check,
)


infra_engineer = Agent(
    role="Infrastructure Engineer",
    goal="Run Terraform init, plan, and (if allowed) apply for bootstrap, dev, and prod so infrastructure is ready for the app.",
    backstory="You are a careful infrastructure engineer. You run terraform init with the correct backend config for each environment, then terraform plan to show changes, and terraform apply only when ALLOW_TERRAFORM_APPLY=1 is set. You work in the repo's infra/bootstrap, infra/envs/dev, infra/envs/prod.",
    tools=[terraform_init, terraform_plan, terraform_apply],
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
    goal="Trigger the deployment so the new image runs in production. Use CodeDeploy (trigger_codedeploy) when DEPLOY_METHOD=codedeploy or when deploy bundle is in S3; use Ansible (run_ansible_deploy) when DEPLOY_METHOD=ansible. If unset, use DEPLOY_METHOD from environment or describe both options.",
    backstory="You are a deployment engineer. You support two deploy methods: (1) CodeDeploy — trigger_codedeploy with application name, deployment group, s3_bucket and s3_key for the deploy bundle. (2) Ansible — run_ansible_deploy with env (prod/dev), ssm_bucket (from terraform output artifacts_bucket). Check DEPLOY_METHOD env (codedeploy or ansible) to decide which to use; if unset, try ansible if ansible dir exists and ssm_bucket is available, else codedeploy if bundle in S3, else report both options.",
    tools=[trigger_codedeploy, run_ansible_deploy, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

verifier_agent = Agent(
    role="Deployment Verifier",
    goal="Verify that the production HTTPS health endpoint returns 200 and that SSM parameters /bluegreen/prod/image_tag and /bluegreen/prod/ecr_repo_name are set correctly.",
    backstory="You are a careful DevOps verifier. You use the HTTP health check and SSM read tools to confirm the deployment is live and configured.",
    tools=[http_health_check, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)
