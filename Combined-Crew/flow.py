"""
Combined-Crew flow: Generate (Full-Orchestrator) then Terraform → Build → Deploy → Verify (Multi-Agent Pipeline).
All five tasks run in sequence; pipeline operates on the generated output_dir.

Agents and tools are defined in agents.py and tools.py (they re-export from Full-Orchestrator and Multi-Agent-Pipeline).
"""
from crewai import Crew, Process, Task

from agents import (
    create_orchestrator_agent,
    infra_engineer,
    build_engineer,
    deploy_engineer,
    verifier_agent,
)
from tools import create_orchestrator_tools, set_repo_root


def create_combined_crew(output_dir: str, requirements: dict, prod_url: str = "", aws_region: str = "us-east-1") -> Crew:
    """
    Create a crew that:
    1. Generate: full project (bootstrap, platform, dev/prod, app, deploy, workflows) into output_dir.
    2. Infra: Terraform init/plan/(apply if ALLOW_TERRAFORM_APPLY=1) in output_dir.
    3. Build: Docker build, ECR push, SSM image_tag in output_dir.
    4. Deploy: CodeDeploy or manual steps.
    5. Verify: Health check (if PROD_URL set) and SSM read.
    """
    # Phase 1: Orchestrator agent (Full-Orchestrator tools)
    gen_tools = create_orchestrator_tools(output_dir, requirements)
    orchestrator_agent = create_orchestrator_agent(gen_tools)

    task_generate = Task(
        description=f"""Generate the full deployment project into: {output_dir}.

Do in order:
1. Generate Terraform bootstrap (generate_bootstrap).
2. Generate platform module (generate_platform).
3. Generate dev environment (generate_dev_env).
4. Generate prod environment (generate_prod_env).
5. Generate app (generate_app).
6. Generate deploy bundle (generate_deploy).
7. Generate GitHub Actions workflows (generate_workflows).
8. Run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod if Terraform is available.
9. Run docker build in app if Docker is available.
10. Write RUN_ORDER.md (tool_write_run_order).

Summarize what was generated and any validation results.""",
        expected_output="Summary: all components generated, validation results, and pointer to RUN_ORDER.md.",
        agent=orchestrator_agent,
    )

    # Pipeline runs on the generated output_dir
    set_repo_root(output_dir)

    health_url = (prod_url.rstrip("/") + "/health") if prod_url else ""
    verify_instruction = (
        f'1. Call http_health_check("{health_url}"). '
        f'2. Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}"). '
        f'3. Call read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}"). '
        "Summarize: health status, image_tag, ecr_repo_name, pass/fail."
    ) if health_url else (
        f'PROD_URL was not set. Skip http_health_check. '
        f'Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}") and '
        f'read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}") and report the values.'
    )

    task_infra = Task(
        description=f"""Run Terraform in the generated repo at: {output_dir}.

Only apply if ALLOW_TERRAFORM_APPLY=1. Otherwise plan only.
1. infra/bootstrap: terraform_init("infra/bootstrap"), terraform_plan("infra/bootstrap"); if allowed, terraform_apply("infra/bootstrap").
2. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"); if allowed, terraform_apply("infra/envs/dev", "dev.tfvars").
3. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"); if allowed, terraform_apply("infra/envs/prod", "prod.tfvars").

Note: backend.hcl and tfvars need bootstrap outputs; if apply fails for that reason, report it and continue. Summarize results.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod.",
        agent=infra_engineer,
        context=[task_generate],
    )

    task_build = Task(
        description=f"""Build and push from the generated repo at {output_dir}.

1. docker_build(app_relative_path="app", tag=e.g. "latest" or a timestamp).
2. read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}") for ECR repo name (if not yet set, report and use a placeholder).
3. ecr_push_and_ssm(ecr_repo_name, image_tag, aws_region="{aws_region}").

Summarize build and push result.""",
        expected_output="Summary: Docker build, ECR push, SSM image_tag update.",
        agent=build_engineer,
        context=[task_infra],
    )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. Use DEPLOY_METHOD (codedeploy or ansible) to choose.

If DEPLOY_METHOD=codedeploy: use trigger_codedeploy(application_name, deployment_group_name, s3_bucket, s3_key, region="{aws_region}").
If DEPLOY_METHOD=ansible: use run_ansible_deploy(env="prod", ssm_bucket=<from terraform output artifacts_bucket>, region="{aws_region}").
If unset: prefer run_ansible_deploy if ansible/ exists and ssm_bucket available; else trigger_codedeploy if bundle in S3; else report both options. Confirm image_tag via read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").""",
        expected_output="Summary: deployment triggered via CodeDeploy or Ansible, or instructions for both and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    task_verify = Task(
        description=f"""Verify deployment. {verify_instruction}""",
        expected_output="Short report: health status (or skipped if no PROD_URL), SSM image_tag, SSM ecr_repo_name, pass/fail.",
        agent=verifier_agent,
        context=[task_deploy],
    )

    return Crew(
        agents=[orchestrator_agent, infra_engineer, build_engineer, deploy_engineer, verifier_agent],
        tasks=[task_generate, task_infra, task_build, task_deploy, task_verify],
        process=Process.sequential,
        verbose=True,
    )
