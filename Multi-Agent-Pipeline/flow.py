"""
Multi-Agent Deploy Pipeline: sequential flow Terraform → Build → Deploy → Verify.
"""
from crewai import Crew, Process, Task

from agents import infra_engineer, build_engineer, deploy_engineer, verifier_agent


def create_pipeline_crew(repo_root: str, prod_url: str, aws_region: str, app_root: str = None) -> Crew:
    """
    Create a crew with four tasks in order:
    1. Infra: Terraform init/plan/(apply if allowed) for bootstrap, dev, prod.
    2. Build: Docker build, ECR push, SSM image_tag update.
    3. Deploy: Trigger CodeDeploy or report deploy steps.
    4. Verify: HTTP health check and SSM read.

    app_root: optional path to app directory (e.g. crew-DevOps/app). When set, build uses this instead of repo_root/app.
    """
    from tools import set_repo_root, set_app_root
    set_repo_root(repo_root)
    set_app_root(app_root)

    health_url = prod_url.rstrip("/") + "/health" if prod_url else ""

    task_infra = Task(
        description=f"""Run Terraform for the repo at: {repo_root}.

Do in order (only apply if ALLOW_TERRAFORM_APPLY=1):
1. infra/bootstrap: terraform_init("infra/bootstrap"), then terraform_plan("infra/bootstrap"). If ALLOW_TERRAFORM_APPLY=1, terraform_apply("infra/bootstrap").
2. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"). If allowed, terraform_apply("infra/envs/dev", "dev.tfvars").
3. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"). If allowed, terraform_apply("infra/envs/prod", "prod.tfvars").

Summarize: what was planned/applied and any errors. If apply was skipped, say so and remind the user to set ALLOW_TERRAFORM_APPLY=1 to apply.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod: success or failure for each, and whether apply was run or skipped.",
        agent=infra_engineer,
    )

    task_build = Task(
        description=f"""Build the app and push to ECR, then update SSM.

1. Run docker_build(app_relative_path="app", tag=something like a timestamp or "latest"). Use a tag you will pass to ECR.
2. Read the ECR repo name: read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}").
3. Call ecr_push_and_ssm(ecr_repo_name=<from SSM>, image_tag=<tag you used>, aws_region="{aws_region}").

If docker or ECR fails, report the error. Summarize: build OK, push OK, SSM image_tag updated.""",
        expected_output="Summary: Docker build result, ECR push result, SSM /bluegreen/prod/image_tag value set. Or clear error message if a step failed.",
        agent=build_engineer,
        context=[task_infra],
    )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. Choose based on DEPLOY_METHOD (env: codedeploy or ansible).

Option A — CodeDeploy (DEPLOY_METHOD=codedeploy or when bundle is in S3): Call trigger_codedeploy(application_name, deployment_group_name, s3_bucket, s3_key, region="{aws_region}"). Get app name and deployment group from Terraform (e.g. bluegreen-prod, bluegreen-prod-dg). Need deploy bundle uploaded to S3 first.

Option B — Ansible (DEPLOY_METHOD=ansible): Call run_ansible_deploy(env="prod", ssm_bucket=<bucket>, ansible_dir="ansible", region="{aws_region}"). ssm_bucket is the S3 bucket for SSM (get from terraform output -raw artifacts_bucket in infra/envs/prod). Requires ansible/ with inventory and playbooks/deploy.yml in the repo.

If DEPLOY_METHOD is not set, use run_ansible_deploy if ansible directory exists and you can get artifacts_bucket (e.g. from user or terraform output); otherwise use trigger_codedeploy if bundle is in S3; else summarize both options and confirm image_tag from read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").""",
        expected_output="Summary: Deployment triggered via CodeDeploy (with deployment ID) or Ansible (playbook result), or clear instructions for both options and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    task_verify = Task(
        description=f"""Verify the deployment is live and configured.

1. Call http_health_check("{health_url}") to check the production health endpoint.
2. Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").
3. Call read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}").

Summarize: health status (OK or error), image_tag value, ecr_repo_name value, and whether verification passed or failed.""",
        expected_output="Short report: health endpoint status, SSM image_tag, SSM ecr_repo_name, and whether verification passed or failed.",
        agent=verifier_agent,
        context=[task_deploy],
    )

    return Crew(
        agents=[infra_engineer, build_engineer, deploy_engineer, verifier_agent],
        tasks=[task_infra, task_build, task_deploy, task_verify],
        process=Process.sequential,
        verbose=True,
    )
