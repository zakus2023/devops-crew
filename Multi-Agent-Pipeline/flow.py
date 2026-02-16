"""
Multi-Agent Deploy Pipeline: sequential flow Terraform → Build → Deploy → Verify.
"""
import os

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
2. After bootstrap apply (if you applied): call update_backend_from_bootstrap() so dev and prod backend.hcl and tfvars get the real tfstate_bucket, tflock_table, and cloudtrail_bucket from bootstrap outputs. Then dev/prod init will find the S3 bucket.
3. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"). If allowed, terraform_apply("infra/envs/dev", "dev.tfvars").
4. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"). If allowed, terraform_apply("infra/envs/prod", "prod.tfvars").

Summarize: what was planned/applied and any errors. If apply was skipped, say so and remind the user to set ALLOW_TERRAFORM_APPLY=1 to apply.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod: success or failure for each, and whether apply was run or skipped.",
        agent=infra_engineer,
    )

    task_build = Task(
        description=f"""Build the app and push to ECR, then update SSM.

1. Use a unique image tag for ECR (e.g. build-YYYYMMDDTHHMMSSZ or build-<timestamp>). Many ECR repos have tag immutability, so avoid "latest" unless you know it is allowed.
2. Run docker_build(app_relative_path="app", tag=<your unique tag>).
3. Read the ECR repo name: read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}").
4. Call ecr_push_and_ssm(ecr_repo_name=<from SSM>, image_tag=<same tag>, aws_region="{aws_region}").

If docker or ECR fails (e.g. tag immutable), retry with a new unique tag. Summarize: build OK, push OK, SSM image_tag updated.""",
        expected_output="Summary: Docker build result, ECR push result, SSM /bluegreen/prod/image_tag value set. Or clear error message if a step failed.",
        agent=build_engineer,
        context=[task_infra],
    )

    # Deploy method is chosen automatically from .env DEPLOY_METHOD (codedeploy | ansible | ssh_script | ecs).
    deploy_method = (os.environ.get("DEPLOY_METHOD") or "").strip().lower()
    if deploy_method == "ssh_script":
        deploy_instruction = (
            f'Use only SSH deploy. Call run_ssh_deploy(env="prod", region="{aws_region}"). '
            f'Requires SSH_KEY_PATH or SSH_PRIVATE_KEY; EC2 tagged Env=prod (or Env=dev), reachable on port 22. Do NOT use Ansible, CodeDeploy, or ECS.'
        )
    elif deploy_method == "ecs":
        deploy_instruction = (
            f'Use only ECS deploy. Get ecs_cluster_name and ecs_service_name: first try get_terraform_output("ecs_cluster_name", "infra/envs/prod") and get_terraform_output("ecs_service_name", "infra/envs/prod"). If either is not found, use read_ssm_parameter("/bluegreen/prod/ecs_cluster_name", region="{aws_region}") and read_ssm_parameter("/bluegreen/prod/ecs_service_name", region="{aws_region}"). If both Terraform outputs and SSM parameters are missing, in your final answer tell the user: ECS is not enabled — set enable_ecs = true in infra/envs/prod/prod.tfvars, run terraform apply for prod (or re-run with ALLOW_TERRAFORM_APPLY=1), then re-run; or set DEPLOY_METHOD=ssh_script in .env to deploy via SSH. When cluster and service are found, call run_ecs_deploy(cluster_name=..., service_name=..., region="{aws_region}"). Do NOT use Ansible, CodeDeploy, or ssh_script.'
        )
    elif deploy_method == "codedeploy":
        deploy_instruction = (
            f'Use only CodeDeploy. Get codedeploy_app and codedeploy_group from get_terraform_output("codedeploy_app", "infra/envs/prod") and get_terraform_output("codedeploy_group", "infra/envs/prod"), then trigger_codedeploy with s3_bucket and s3_key. Do NOT use Ansible, ECS, or ssh_script.'
        )
    else:
        # ansible or unset
        deploy_instruction = (
            f'Use only Ansible. Get get_terraform_output("artifacts_bucket", "infra/envs/prod"), then run_ansible_deploy(env="prod", ssm_bucket=<that value>, ansible_dir="ansible", region="{aws_region}"). If that fails, in your final answer suggest setting DEPLOY_METHOD=ssh_script or codedeploy or ecs in .env and re-running.'
        )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. You must actually run a deploy; do not stop to ask the user for confirmation when you can get values from tools.

Deploy method for this run (from .env DEPLOY_METHOD): **{deploy_method or "ansible"}**

**{deploy_instruction}**""",
        expected_output="Summary: Deployment triggered (CodeDeploy ID, Ansible result, SSH deploy per-instance status, or ECS update), or clear instructions and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    # Wait before health check so the app is ready: ECS needs longest (new task); codedeploy/ssh/ansible need a short buffer after restart.
    if deploy_method == "ecs":
        wait_before_health = "First call wait_seconds(90) so the new ECS task can become healthy, then call"
    elif deploy_method == "codedeploy":
        wait_before_health = "First call wait_seconds(60) so the CodeDeploy rollout can complete, then call"
    elif deploy_method == "ssh_script":
        wait_before_health = "First call wait_seconds(30) so the app can finish restarting on EC2, then call"
    elif deploy_method == "ansible":
        wait_before_health = "First call wait_seconds(30) so the app can finish restarting after Ansible, then call"
    else:
        wait_before_health = "Call"
    verify_instruction = (
        f'Deploy method for this run: **{deploy_method or "ansible"}**. '
        f'{wait_before_health} http_health_check("{health_url}"). '
        f'Then call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}") and read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}"). '
        "Summarize: health status (OK or error), image_tag value, ecr_repo_name value, and whether verification passed or failed."
    )
    task_verify = Task(
        description=f"""Verify the deployment is live and configured.

{verify_instruction}""",
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
