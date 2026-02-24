"""
Combined-Crew flow: Generate (Full-Orchestrator) then Terraform → Build → Deploy → Verify (Multi-Agent Pipeline).
All five tasks run in sequence; pipeline operates on the generated output_dir.

Agents and tools are defined in agents.py and tools.py (they re-export from Full-Orchestrator and Multi-Agent-Pipeline).
Deploy methods: ansible | ssh_script | ecs (from .env DEPLOY_METHOD, same as Multi-Agent-Pipeline).
"""
import os

from crewai import Crew, Process, Task

from agents import (
    create_orchestrator_agent,
    infra_engineer,
    build_engineer,
    deploy_engineer,
    verifier_agent,
)
from combined_tools import create_orchestrator_tools, set_repo_root


def create_combined_crew(
    output_dir: str,
    requirements: dict,
    prod_url: str = "",
    aws_region: str = "us-east-1",
    app_dir: str | None = None,
) -> Crew:
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

    # Pipeline runs on the generated output_dir — must update the "tools" module the pipeline agents use
    # (sys.modules["tools"]), not the separate instance from combined_tools
    import sys
    tools_mod = sys.modules.get("tools")
    if tools_mod is not None and hasattr(tools_mod, "set_repo_root"):
        tools_mod.set_repo_root(output_dir)
        if hasattr(tools_mod, "set_app_root"):
            tools_mod.set_app_root(app_dir.strip() if app_dir else None)
    else:
        set_repo_root(output_dir)

    # Strip www. from prod_url so health check uses the actual deployed domain (e.g. app.my-iifb.click)
    _prod = (prod_url or "").strip().rstrip("/")
    if _prod and "://www." in _prod:
        _prod = _prod.replace("://www.", "://", 1)
    health_url = (_prod + "/health") if _prod else ""
    deploy_method = (os.environ.get("DEPLOY_METHOD") or "").strip().lower()
    if deploy_method == "ecs":
        wait_before_health = "First call wait_seconds(90) so the new ECS task can become healthy, then call"
    elif deploy_method == "ssh_script":
        wait_before_health = "First call wait_seconds(30) so the app can finish restarting on EC2, then call"
    elif deploy_method in ("ansible", ""):
        wait_before_health = "First call wait_seconds(30) so the app can finish restarting after deploy, then call"
    else:
        wait_before_health = "Call"
    fallback = f'"{health_url}"' if health_url else "none"
    verify_instruction = (
        f'1. Get prod URL: call get_terraform_output("https_url", "infra/envs/prod"). '
        f'If that returns a URL (e.g. https://app.example.com), use it + "/health" for the health check. '
        f'Otherwise use fallback {fallback} (or skip health check if none). Use the Terraform URL when available — it matches the deployed domain (often without www). '
        f'2. {wait_before_health} http_health_check(<url from step 1>). '
        f'3. Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}"). '
        f'4. Call read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}"). '
        "Summarize: health status, image_tag, ecr_repo_name, pass/fail. "
        "If health check fails with DNS/connection error: Terraform prod apply may not have completed (no ALB, EC2, or Route53 record), or the domain nameservers may not delegate to Route53. Ensure Terraform apply completed and domain NS records point to the hosted zone."
    )

    task_infra = Task(
        description=f"""Run Terraform in the generated repo at: {output_dir}.

Only apply if ALLOW_TERRAFORM_APPLY=1. Otherwise plan only.
0. BEFORE dev/prod apply: call run_resolve_aws_limits(region="{aws_region}", release_eips=True) and run_remove_terraform_blockers(region="{aws_region}") to free EIP quota and remove CloudTrail conflicts. Do this automatically so Terraform apply can succeed.
1. infra/bootstrap: terraform_init("infra/bootstrap"), terraform_plan("infra/bootstrap"); if allowed, terraform_apply("infra/bootstrap").
2. After bootstrap apply (only if you applied successfully): call update_backend_from_bootstrap() so dev and prod backend.hcl and tfvars get the real tfstate_bucket, tflock_table, and cloudtrail_bucket from bootstrap outputs. If you skipped apply, do NOT call it.
3. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"); if allowed, call run_resolve_aws_limits and run_remove_terraform_blockers, then terraform_apply("infra/envs/dev", "dev.tfvars"). If apply fails with EntityAlreadyExists for IAM Role, call run_import_platform_iam_on_conflict("infra/envs/dev", "dev.tfvars") then retry. If apply fails with limit/conflict errors, run cleanup and retry.
4. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"); if allowed, call run_resolve_aws_limits and run_remove_terraform_blockers, then terraform_apply("infra/envs/prod", "prod.tfvars"). If apply fails with EntityAlreadyExists for IAM Role, call run_import_platform_iam_on_conflict("infra/envs/prod", "prod.tfvars") then retry terraform_apply. If apply fails with limit/conflict errors, run cleanup and retry. If apply times out or fails partway (e.g. only bastion created), run terraform_apply again.
5. Ensure Terraform apply completes fully so ASG, app instances, ALB, target groups, and Route53 are created — otherwise Deploy and Verify will fail.

Note: backend.hcl and tfvars need bootstrap outputs. Summarize results.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod.",
        agent=infra_engineer,
        context=[task_generate],
    )

    task_build = Task(
        description=f"""Build and push from the generated repo at {output_dir}.

1. docker_build(app_relative_path="app", tag=e.g. "latest" or a timestamp).
2. Read ECR repo name: read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}"). If ParameterNotFound, try get_terraform_output("ecr_repo", "infra/envs/prod").
3. ecr_push_and_ssm(ecr_repo_name, image_tag, aws_region="{aws_region}").

Summarize build and push result.""",
        expected_output="Summary: Docker build, ECR push, SSM image_tag update.",
        agent=build_engineer,
        context=[task_infra],
    )

    # Deploy method from .env (ansible | ssh_script | ecs) — matches Multi-Agent-Pipeline
    deploy_method = (os.environ.get("DEPLOY_METHOD") or "").strip().lower()
    if deploy_method == "ssh_script":
        deploy_instruction = (
            f'Use only SSH deploy. Call run_ssh_deploy(env="prod", region="{aws_region}"). '
            f'Requires SSH_KEY_PATH or SSH_PRIVATE_KEY in .env; EC2 tagged Env=prod (or Env=dev), reachable on port 22. '
            f'Bastion and key_name are auto-injected when DEPLOY_METHOD=ssh_script (set KEY_NAME in .env). '
            f'Do NOT use Ansible or ECS.'
        )
    elif deploy_method == "ecs":
        deploy_instruction = (
            f'Use only ECS deploy. Get ecs_cluster_name and ecs_service_name: first try get_terraform_output("ecs_cluster_name", "infra/envs/prod") and get_terraform_output("ecs_service_name", "infra/envs/prod"). '
            f'If either is not found, use read_ssm_parameter("/bluegreen/prod/ecs_cluster_name", region="{aws_region}") and read_ssm_parameter("/bluegreen/prod/ecs_service_name", region="{aws_region}"). '
            f'If both are missing, tell the user: set enable_ecs=true in requirements.json prod, re-generate and terraform apply; or set DEPLOY_METHOD=ssh_script. '
            f'When cluster and service are found, call run_ecs_deploy(cluster_name=..., service_name=..., region="{aws_region}"). Do NOT use Ansible or ssh_script.'
        )
    else:
        # ansible or unset
        deploy_instruction = (
            f'Use only Ansible. Get get_terraform_output("artifacts_bucket", "infra/envs/prod"), then run_ansible_deploy(env="prod", ssm_bucket=<that value>, ansible_dir="ansible", region="{aws_region}"). '
            f'If that fails (e.g. no hosts matched), suggest setting DEPLOY_METHOD=ssh_script in .env (and enable_bastion=true, key_name in requirements prod for bastion) or DEPLOY_METHOD=ecs.'
        )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. Use DEPLOY_METHOD from .env: ansible | ssh_script | ecs.

Deploy method for this run (from .env DEPLOY_METHOD): **{deploy_method or "ansible"}**

**{deploy_instruction}**""",
        expected_output="Summary: Deployment triggered (Ansible result, SSH deploy per-instance status, or ECS update), or clear instructions and current image_tag.",
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
