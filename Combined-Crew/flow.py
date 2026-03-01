"""
Combined-Crew flow: Generate (Full-Orchestrator) then Terraform → Build → Deploy → Verify (Multi-Agent Pipeline).
All five tasks run in sequence; pipeline operates on the generated output_dir.

Agents and tools are defined in agents.py and tools.py (they re-export from Full-Orchestrator and Multi-Agent-Pipeline).
Deploy methods: ansible | ssh_script | ecs. Priority: explicit param (UI/CLI) first, then DEPLOY_METHOD from .env.
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
from combined_tools import create_orchestrator_tools, set_repo_root, set_app_root, set_project


def create_combined_crew(
    output_dir: str,
    requirements: dict,
    prod_url: str = "",
    aws_region: str = "us-east-1",
    app_dir: str | None = None,
    deploy_method: str | None = None,
) -> Crew:
    """
    Create a crew that:
    1. Generate: full project (bootstrap, platform, dev/prod, app, deploy, workflows) into output_dir.
    2. Infra: Terraform init/plan/(apply if ALLOW_TERRAFORM_APPLY=1) in output_dir.
    3. Build: Docker build, ECR push, SSM image_tag in output_dir.
    4. Deploy: ssh_script, ansible (SSM), or ecs.
    5. Verify: Health check (if PROD_URL set) and SSM read.
    """
    # Project from requirements — SSM paths are /{project}/prod/image_tag etc. (must match Terraform)
    project = (requirements.get("project") or "bluegreen")
    if isinstance(project, str):
        project = project.strip() or "bluegreen"
    else:
        project = "bluegreen"

    # Resolve output_dir to absolute path (avoids path resolution issues on HF Space)
    output_dir_abs = os.path.abspath(os.path.expanduser(output_dir))

    # Phase 1: Orchestrator agent (Full-Orchestrator tools)
    gen_tools = create_orchestrator_tools(output_dir_abs, requirements)
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
7. Run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod if Terraform is available.
8. Run docker build in app if Docker is available.
9. Write RUN_ORDER.md (tool_write_run_order).

Summarize what was generated and any validation results.""",
        expected_output="Summary: all components generated, validation results, and pointer to RUN_ORDER.md.",
        agent=orchestrator_agent,
    )

    # Pipeline runs on the generated output_dir — must update the "tools" module the pipeline agents use
    import sys
    tools_mod = sys.modules.get("tools")
    if tools_mod is None:
        for _name, _mod in sys.modules.items():
            if _mod is not None and hasattr(_mod, "set_repo_root") and hasattr(_mod, "set_app_root"):
                tools_mod = _mod
                break
    if tools_mod is not None and hasattr(tools_mod, "set_repo_root"):
        tools_mod.set_repo_root(output_dir_abs)
        if hasattr(tools_mod, "set_app_root"):
            tools_mod.set_app_root(app_dir.strip() if app_dir else None)
        if hasattr(tools_mod, "set_project"):
            tools_mod.set_project(project)
    else:
        set_repo_root(output_dir_abs)
        if app_dir and set_app_root is not None:
            set_app_root(app_dir.strip())
        if set_project is not None:
            set_project(project)

    ssm_image_tag = f"/{project}/prod/image_tag"
    ssm_ecr_repo = f"/{project}/prod/ecr_repo_name"
    ssm_ecs_cluster = f"/{project}/prod/ecs_cluster_name"
    ssm_ecs_service = f"/{project}/prod/ecs_service_name"
    # Use dedicated tools (read_ssm_image_tag, read_ssm_ecr_repo_name) so the agent cannot hallucinate wrong paths.

    # Strip www. from prod_url so health check uses the actual deployed domain (e.g. app.my-iifb.click)
    _prod = (prod_url or "").strip().rstrip("/")
    if _prod and "://www." in _prod:
        _prod = _prod.replace("://www.", "://", 1)
    health_url = (_prod + "/health") if _prod else ""
    # Priority: explicit param (UI/CLI input) first, then DEPLOY_METHOD from .env
    deploy_method = (deploy_method or os.environ.get("DEPLOY_METHOD") or "").strip().lower()
    # Normalize invalid deploy methods (ecs_script->ecs, shs_script->ssh_script)
    if deploy_method == "ecs_script":
        deploy_method = "ecs"
    elif deploy_method == "shs_script":
        deploy_method = "ssh_script"
    elif deploy_method not in ("ansible", "ssh_script", "ecs"):
        deploy_method = "ansible"
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
        f'2. {wait_before_health} http_health_check(<url from step 1>). If health check fails (DNS/connection error), note it and continue — do NOT stop. '
        f'3. Always call read_ssm_image_tag(region="{aws_region}"). '
        f'4. Always call read_ssm_ecr_repo_name(region="{aws_region}"). '
        f'Use these dedicated tools — do NOT use read_ssm_parameter with hand-constructed paths. Report the exact parameter names: {ssm_image_tag} and {ssm_ecr_repo}. '
        "Always run steps 3 and 4 even when step 2 fails. Summarize: health status, image_tag, ecr_repo_name, pass/fail. "
        "If health check fails with DNS/connection error: Terraform prod apply may not have completed (no ALB, EC2, or Route53 record), or the domain nameservers may not delegate to Route53. Still report SSM results."
    )

    task_infra = Task(
        description=f"""Run the full Terraform pipeline in the generated repo at: {output_dir}.

**Primary action:** Call run_full_infra_pipeline(region="{aws_region}"). This runs everything automatically in the correct order:
- resolve_aws_limits and remove_terraform_blockers (free EIP quota, remove CloudTrail conflicts)
- bootstrap: init, plan, apply (if ALLOW_TERRAFORM_APPLY=1)
- update_backend_from_bootstrap (writes tfstate_bucket, tflock_table, cloudtrail_bucket to dev/prod)
- dev: init, plan, apply (with IAM import retry on EntityAlreadyExists)
- prod: init, plan, apply (with IAM import retry on EntityAlreadyExists)

Only apply runs when ALLOW_TERRAFORM_APPLY=1; otherwise plan only. Summarize the result.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod.",
        agent=infra_engineer,
        context=[task_generate],
    )

    app_note = f" Custom app directory is set: {app_dir}" if app_dir else ""
    task_build = Task(
        description=f"""Build and push from the generated repo at {output_dir}.{app_note}

1. docker_build(app_relative_path="app", tag=e.g. "latest" or a timestamp). When a custom app directory is set, docker_build uses it automatically (folder must contain Dockerfile).
2. Read ECR repo name: read_ssm_ecr_repo_name(region="{aws_region}"). If ParameterNotFound, try get_terraform_output("ecr_repo", "infra/envs/prod").
3. ecr_push_and_ssm(ecr_repo_name, image_tag, aws_region="{aws_region}").

**When Docker is unavailable** (e.g. Hugging Face Space): Use automatic EC2 build runner — do NOT ask for manual steps:
- Call ec2_docker_build_and_push(ecr_repo_name, app_relative_path="app", region="{aws_region}"). This zips the app, uploads to S3, runs SSM command on the EC2 build runner to docker build, push to ECR, and updates SSM image_tag.
- If ec2_docker_build_and_push fails (e.g. build runner not yet applied): fall back to read_pre_built_image_tag() or ecr_list_image_tags(); if a tag exists, call write_ssm_image_tag(tag, region="{aws_region}").

Summarize build and push result.""",
        expected_output="Summary: Docker build, ECR push, SSM image_tag update. Or fallback: write_ssm_image_tag when Docker unavailable.",
        agent=build_engineer,
        context=[task_infra],
    )

    # Use same deploy_method as above (param first, then env)
    if deploy_method == "ssh_script":
        deploy_instruction = (
            f'Use only SSH deploy. You MUST call run_ssh_deploy(env="prod", region="{aws_region}"). '
            f'Requires SSH_KEY_PATH or SSH_PRIVATE_KEY in .env; EC2 tagged Env=prod (or Env=dev), reachable on port 22. '
            f'Bastion and key_name are auto-injected when DEPLOY_METHOD=ssh_script (set KEY_NAME in .env). '
            f'Do NOT use Ansible or ECS.'
        )
    elif deploy_method == "ecs":
        deploy_instruction = (
            f'Use only ECS deploy. Get ecs_cluster_name and ecs_service_name: first try get_terraform_output("ecs_cluster_name", "infra/envs/prod") and get_terraform_output("ecs_service_name", "infra/envs/prod"). '
            f'If either is not found, use read_ssm_parameter("{ssm_ecs_cluster}", region="{aws_region}") and read_ssm_parameter("{ssm_ecs_service}", region="{aws_region}"). '
            f'If both are missing, tell the user: set enable_ecs=true in requirements.json prod, re-generate and terraform apply; or set DEPLOY_METHOD=ssh_script. '
            f'When cluster and service are found, you MUST call run_ecs_deploy(cluster_name=..., service_name=..., region="{aws_region}"). Do NOT use Ansible or ssh_script.'
        )
    else:
        # ansible or unset
        deploy_instruction = (
            f'Use only Ansible. Get get_terraform_output("artifacts_bucket", "infra/envs/prod"), then you MUST call run_ansible_deploy(env="prod", ssm_bucket=<that value>, ansible_dir="ansible", region="{aws_region}"). '
            f'If that fails (e.g. no hosts matched), suggest setting DEPLOY_METHOD=ssh_script in .env (and enable_bastion=true, key_name in requirements prod for bastion) or DEPLOY_METHOD=ecs.'
        )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. You MUST actually call the deploy tool — do not stop to ask the user for confirmation when you can get values from tools. Priority: UI input first, then DEPLOY_METHOD from .env.

Deploy method for this run: **{deploy_method or "ansible"}**

**{deploy_instruction}**""",
        expected_output="Summary: Deployment triggered (Ansible result, SSH deploy per-instance status, or ECS update), or clear instructions and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    task_verify = Task(
        description=f"""Verify deployment. {verify_instruction}""",
        expected_output=f"Short report: health status (or skipped if no PROD_URL), SSM {ssm_image_tag} and {ssm_ecr_repo} values, pass/fail.",
        agent=verifier_agent,
        context=[task_deploy],
    )

    return Crew(
        agents=[orchestrator_agent, infra_engineer, build_engineer, deploy_engineer, verifier_agent],
        tasks=[task_generate, task_infra, task_build, task_deploy, task_verify],
        process=Process.sequential,
        verbose=True,
    )
