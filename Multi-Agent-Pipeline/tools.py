"""
Tools for the Multi-Agent Deploy Pipeline: Terraform, Build, Deploy, Verify.

This module provides the tools that the four pipeline agents (Infra, Build, Deploy, Verifier)
call to run Terraform, Docker, ECR, SSM, Ansible, and health checks. All paths
are relative to repo_root (the deployment project root, e.g. Full-Orchestrator/output).
flow.py calls set_repo_root() and set_app_root() before creating the crew so tools resolve
paths correctly.

Tool groups:
  - Terraform: terraform_init, terraform_plan, terraform_apply, update_backend_from_bootstrap (infra agent).
  - Build:     docker_build, ecr_push_and_ssm (build agent).
  - Deploy:    get_terraform_output, run_ansible_deploy, run_ssh_deploy, run_ecs_deploy (deploy agent; DEPLOY_METHOD picks one).
  - Shared:    read_ssm_parameter (build, deploy, verifier).
  - Verify:    http_health_check (verifier).
"""
import copy
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Optional

import requests

# CrewAI's @tool decorator gives each function a description the LLM uses to choose and call it.
# Fallback if crewai-tools is not installed (e.g. in tests).
try:
    from crewai.tools import tool
except ImportError:
    def tool(desc):
        def deco(fn):
            fn.description = desc
            return fn
        return deco

# --- Repo and app root (set by flow.py when creating the crew) ---
# REPO_ROOT: path to the deployment project (e.g. Full-Orchestrator/output). Terraform and
# Ansible paths are under this (infra/bootstrap, infra/envs/dev|prod, ansible/).
_REPO_ROOT: Optional[str] = None
# APP_ROOT: optional path to the app directory for Docker build. When set (e.g. crew-DevOps/app),
# docker_build runs there instead of repo_root/app. run.py sets this when crew-DevOps/app exists.
_APP_ROOT: Optional[str] = None
# PROJECT: SSM parameter prefix. Terraform creates /{project}/{env}/image_tag etc. Default "bluegreen".
_PROJECT: str = "bluegreen"


def _ssm_path(env: str, name: str) -> str:
    """SSM parameter path matching Terraform: /{project}/{env}/{name}."""
    return f"/{_PROJECT}/{env}/{name}"


def _call_tool(tool_fn, *args, **kwargs):
    """Call a CrewAI tool's underlying function. Use when one tool must invoke another."""
    fn = getattr(tool_fn, "func", tool_fn)
    return fn(*args, **kwargs)


def set_repo_root(path: str) -> None:
    """
Tells the pipeline which folder is your "project". That folder contains
    infra/, app/, deploy/, ansible/. The pipeline runs all Terraform and Ansible
    commands inside that folder.     You don't call this yourself — run.py does it with
    REPO_ROOT.
    """
    # We're going to change the global variable _REPO_ROOT (so other functions see it).
    global _REPO_ROOT
    # Store the path the caller passed in (the project folder).
    _REPO_ROOT = path


def set_app_root(path: Optional[str]) -> None:
    """
    Optional — "When building the Docker image, use this folder as the app
    instead of project/app." Useful when your app lives in crew-DevOps/app. run.py
    sets this for you.
    """
    # We're going to change the global variable _APP_ROOT.
    global _APP_ROOT
    # Store the path (or None to mean "use repo_root/app").
    _APP_ROOT = path


def set_project(project: str) -> None:
    """
    Set the project name for SSM parameter paths. Terraform creates /{project}/{env}/image_tag etc.
    Must match requirements.json "project" (e.g. bluegreen, crew-devops). Default is bluegreen.
    """
    global _PROJECT
    _PROJECT = (project or "bluegreen").strip() or "bluegreen"


def get_repo_root() -> str:
    """
    Returns the path that was set by set_repo_root. Each tool uses this to
    know where to run commands (e.g. where is infra/bootstrap, where is the app).
    If never set, returns the parent of Multi-Agent-Pipeline.
    """
    # If nobody set the repo root yet, use the parent of this file's folder (crew-DevOps).
    if _REPO_ROOT is None:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Otherwise return the path that was set.
    return _REPO_ROOT


def get_app_root() -> Optional[str]:
    """
    If set, docker_build uses this path for the app; else build from
    repo_root/app.
    """
    # Just return whatever was set (or None).
    return _APP_ROOT


# ---------------------------------------------------------------------------
# Terraform tools (used by Infra Engineer agent)
# ---------------------------------------------------------------------------

@tool("Run 'terraform init' in a Terraform directory. Input: relative_path from repo root, e.g. 'infra/bootstrap' or 'infra/envs/dev'. Optional backend_config, e.g. 'backend.hcl' for envs.")
def terraform_init(relative_path: str, backend_config: Optional[str] = None) -> str:
    """
    "Prepare Terraform in this folder." Runs `terraform init` in a subfolder
    of your project (e.g. infra/bootstrap or infra/envs/dev). If you pass
    backend_config (e.g. "backend.hcl"), Terraform uses that file to know where to
    store state (S3 bucket). You must run init before plan or apply.
    """
    # Get the path to the project folder (e.g. Full-Orchestrator/output).
    root = get_repo_root()
    # Build the full path where we will run Terraform, e.g. project_folder/infra/bootstrap.
    work_dir = os.path.join(root, relative_path)
    # If that folder doesn't exist, stop and return an error message; don't run Terraform.
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    # Start building the command we'll run: terraform init.
    cmd = ["terraform", "init"]
    # If the caller passed a backend config file (e.g. "backend.hcl"), add options so Terraform knows where to store state (e.g. S3).
    if backend_config:
        cmd.extend(["-backend-config", backend_config, "-reconfigure"])
    try:
        # Run the terraform init command in work_dir; capture what it prints. Allow 300s for S3 backend + provider download.
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        # If Terraform exited with code 0 (success), return a short "OK" message.
        if result.returncode == 0:
            return f"terraform init in {relative_path}: OK"
        # Otherwise return a message that includes the error output.
        return f"terraform init in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    # If "terraform" isn't a program on this machine, return a friendly message.
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    # Any other error (e.g. permission, timeout) — return that error.
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Run 'terraform plan' in a Terraform directory. Input: relative_path (e.g. infra/envs/prod), var_file (e.g. prod.tfvars) optional.")
def terraform_plan(relative_path: str, var_file: Optional[str] = None) -> str:
    """
    "Show me what would change, but don't change anything." Runs
    `terraform plan` so you see what Terraform would create or update (e.g. new EC2
    instances, security groups). var_file (e.g. "prod.tfvars") passes variable values.
    Safe to run anytime.
    """
    # Get the project folder path.
    root = get_repo_root()
    # Build the full path to the Terraform directory (e.g. project/infra/envs/prod).
    work_dir = os.path.join(root, relative_path)
    # If that folder doesn't exist, return an error and stop.
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    # Build the command: terraform plan.
    cmd = ["terraform", "plan"]
    # If the caller passed a var file (e.g. prod.tfvars), resolve to absolute path and add it.
    if var_file:
        var_file_path = os.path.join(work_dir, var_file)
        if os.path.isfile(var_file_path):
            cmd.extend(["-var-file", os.path.abspath(var_file_path)])
    try:
        # Run terraform plan in work_dir; capture output; wait up to 300 seconds.
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        # If Terraform succeeded, return OK and the last 2000 characters of output.
        if result.returncode == 0:
            return f"terraform plan in {relative_path}: OK\n{result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout}"
        # Otherwise return FAIL and the error output.
        return f"terraform plan in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    # If terraform is not installed, return a friendly message.
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    # Any other error — return it.
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Run 'terraform apply -auto-approve' in a Terraform directory. Only runs if ALLOW_TERRAFORM_APPLY=1. Input: relative_path, var_file optional.")
def terraform_apply(relative_path: str, var_file: Optional[str] = None) -> str:
    """
    "Actually create or update the infrastructure." Runs
    `terraform apply -auto-approve`. Only runs if you set ALLOW_TERRAFORM_APPLY=1 in
    the environment; otherwise it returns a message saying "set that variable to allow
    apply." This is the safety switch so the pipeline doesn't change infra without
    your permission.
    """
    # Safety check: if the env var is not set to 1, refuse to apply and return a message.
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        return "terraform apply skipped: set ALLOW_TERRAFORM_APPLY=1 to allow apply. Run terraform plan first to review changes."
    # Get the project folder path.
    root = get_repo_root()
    # Build the full path to the Terraform directory.
    work_dir = os.path.join(root, relative_path)
    # If that folder doesn't exist, return an error and stop.
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    # Build the command: terraform apply -auto-approve (no interactive "yes" prompt).
    cmd = ["terraform", "apply", "-auto-approve"]
    # If the caller passed a var file, resolve to absolute path and verify it exists.
    if var_file:
        var_file_path = os.path.join(work_dir, var_file)
        if not os.path.isfile(var_file_path):
            return f"Error: var file not found: {var_file_path} (required for dev/prod apply)"
        cmd.extend(["-var-file", os.path.abspath(var_file_path)])
    try:
        # Run terraform apply in work_dir. Prod apply (NAT, ALB, ASG, CodeDeploy) can take 8-15 min.
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
        # If Terraform succeeded, return OK.
        if result.returncode == 0:
            return f"terraform apply in {relative_path}: OK"
        # Otherwise return FAIL and the error output.
        return f"terraform apply in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    # If terraform is not installed, return a friendly message.
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    # Any other error — return it.
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("After bootstrap apply: read tfstate_bucket, tflock_table, cloudtrail_bucket from infra/bootstrap terraform output and write them into infra/envs/dev and infra/envs/prod backend.hcl and tfvars. Call this after terraform_apply('infra/bootstrap') so dev/prod init can use the real bucket. No input.")
def update_backend_from_bootstrap() -> str:
    """
    After the first bootstrap apply, dev and prod need the real S3 bucket and DynamoDB table
    in their backend.hcl, and cloudtrail_bucket in their tfvars. This tool runs
    `terraform output -raw` in infra/bootstrap and updates the four files so you don't have to
    do it manually. Call it after a successful bootstrap apply, before running init for dev/prod.
    """
    # Get the project folder path.
    root = get_repo_root()
    # Path to the bootstrap Terraform directory.
    bootstrap_dir = os.path.join(root, "infra", "bootstrap")
    if not os.path.isdir(bootstrap_dir):
        return f"Error: bootstrap directory not found: {bootstrap_dir}"
    # Helper: run terraform output -raw <name> in bootstrap_dir and return the value or None.
    # Reject Terraform warnings (e.g. "No outputs found") which get written to stdout when
    # bootstrap hasn't been applied — they would corrupt backend.hcl.
    def _output(name: str) -> Optional[str]:
        try:
            r = subprocess.run(
                ["terraform", "output", "-raw", name],
                cwd=bootstrap_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if r.returncode != 0:
                return None
            val = (r.stdout or "").strip()
            if not val:
                return None
            # Reject Terraform warning text or multi-line output (invalid for backend.hcl).
            if "Warning" in val or "No outputs found" in val or "\n" in val:
                return None
            # Reject box-drawing / control chars (Terraform UI artifacts).
            if any(c in val for c in ("╷", "╵", "│", "\x1b")):
                return None
            # Bucket/table names: alphanumeric, hyphens, underscores, dots; reasonable length.
            if len(val) > 128 or not all(c.isalnum() or c in "-_.%" for c in val):
                return None
            return val
        except Exception:
            pass
        return None
    # Read the three bootstrap outputs we need.
    tfstate_bucket = _output("tfstate_bucket")
    tflock_table = _output("tflock_table")
    cloudtrail_bucket = _output("cloudtrail_bucket")
    if not tfstate_bucket or not tflock_table:
        return "Error: could not read tfstate_bucket or tflock_table from infra/bootstrap. Run terraform apply in infra/bootstrap first."
    if not cloudtrail_bucket:
        return "Error: could not read cloudtrail_bucket from infra/bootstrap. Run terraform apply in infra/bootstrap first."
    updated = []
    # Update backend.hcl for dev and prod: set bucket and dynamodb_table.
    for env in ("dev", "prod"):
        backend_path = os.path.join(root, "infra", "envs", env, "backend.hcl")
        if not os.path.isfile(backend_path):
            continue
        with open(backend_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Replace bucket = "..." and dynamodb_table = "..." with the bootstrap values.
        content = re.sub(r'(\s*bucket\s*=\s*)"[^"]*"', f'\\1"{tfstate_bucket}"', content)
        content = re.sub(r'(\s*dynamodb_table\s*=\s*)"[^"]*"', f'\\1"{tflock_table}"', content)
        with open(backend_path, "w", encoding="utf-8") as f:
            f.write(content)
        updated.append(f"infra/envs/{env}/backend.hcl")
    # Update tfvars for dev and prod: set cloudtrail_bucket.
    tfvars = [("dev", "dev.tfvars"), ("prod", "prod.tfvars")]
    for env, fname in tfvars:
        tfvars_path = os.path.join(root, "infra", "envs", env, fname)
        if not os.path.isfile(tfvars_path):
            continue
        with open(tfvars_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'(\s*cloudtrail_bucket\s*=\s*)"[^"]*"', f'\\1"{cloudtrail_bucket}"', content)
        with open(tfvars_path, "w", encoding="utf-8") as f:
            f.write(content)
        updated.append(f"infra/envs/{env}/{fname}")
    return f"update_backend_from_bootstrap: OK. tfstate_bucket={tfstate_bucket}, tflock_table={tflock_table}, cloudtrail_bucket={cloudtrail_bucket}. Updated: {', '.join(updated)}"


def _get_scripts_dir() -> str:
    """Path to Combined-Crew/scripts (sibling of Multi-Agent-Pipeline)."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Combined-Crew", "scripts")


@tool("Run the full infra pipeline automatically: resolve limits, remove blockers, bootstrap init/plan/apply, update backend, dev init/plan/apply, prod init/plan/apply. Handles IAM import retry on conflict. Input: region (default us-east-1). Call this instead of individual terraform steps.")
def run_full_infra_pipeline(region: str = "us-east-1") -> str:
    """
    Runs the complete Terraform pipeline in the correct order. No manual steps needed.
    1. resolve_aws_limits + remove_terraform_blockers
    2. bootstrap: init, plan, apply (if ALLOW_TERRAFORM_APPLY=1)
    3. update_backend_from_bootstrap
    4. dev: init, plan, apply (if allowed); retry with IAM import on EntityAlreadyExists
    5. prod: init, plan, apply (if allowed); retry with IAM import on EntityAlreadyExists
    """
    allow_apply = os.environ.get("ALLOW_TERRAFORM_APPLY") == "1"
    lines = []

    def _run(tool_fn, *args, **kwargs):
        r = _call_tool(tool_fn, *args, **kwargs)
        lines.append(r)
        return r

    # 0. Resolve limits and remove blockers
    _run(run_resolve_aws_limits, region=region, release_eips=True)
    _run(run_remove_terraform_blockers, region=region)

    # 1. Bootstrap
    r = _run(terraform_init, "infra/bootstrap")
    if "FAIL" in r:
        return "\n".join(lines)
    _run(terraform_plan, "infra/bootstrap")
    if allow_apply:
        r = _run(terraform_apply, "infra/bootstrap")
        if "FAIL" in r:
            return "\n".join(lines)

    # 2. Update backend for dev/prod
    r = _run(update_backend_from_bootstrap)
    if "Error:" in r:
        return "\n".join(lines)

    def _apply_env(env: str, var_file: str, max_retries: int = 2) -> str:
        """Apply env with IAM import retry on conflict, and generic retry on failure (e.g. timeout, partial apply)."""
        path = f"infra/envs/{env}"
        for attempt in range(max_retries):
            _run(run_resolve_aws_limits, region=region, release_eips=True)
            _run(run_remove_terraform_blockers, region=region)
            r = _run(terraform_apply, path, var_file)
            if "FAIL" not in r:
                return r
            # Already-exists conflicts: import into state and retry (IAM roles, IAM policy, CloudWatch, CodeDeploy)
            if any(x in r for x in ("EntityAlreadyExists", "ResourceAlreadyExistsException", "ApplicationAlreadyExistsException", "already exists")):
                _run(run_import_platform_iam_on_conflict, path, var_file)
                _run(run_import_existing_platform_resources, path, var_file)
                r = _run(terraform_apply, path, var_file)
                if "FAIL" not in r:
                    return r
            # Other failure (timeout, partial apply): wait and retry
            if attempt < max_retries - 1:
                lines.append(f"{env} apply attempt {attempt + 1} failed; retrying in 30s...")
                time.sleep(30)
        return r

    # 3. Dev
    r = _run(terraform_init, "infra/envs/dev", "backend.hcl")
    if "FAIL" in r:
        return "\n".join(lines)
    _run(terraform_plan, "infra/envs/dev", "dev.tfvars")
    if allow_apply:
        _apply_env("dev", "dev.tfvars")

    # 4. Prod (critical for ssh_script/ecs deploy — must complete so prod EC2/ECS exist)
    r = _run(terraform_init, "infra/envs/prod", "backend.hcl")
    if "FAIL" in r:
        return "\n".join(lines)
    _run(terraform_plan, "infra/envs/prod", "prod.tfvars")
    prod_apply_ok = True
    if allow_apply:
        r = _apply_env("prod", "prod.tfvars", max_retries=3)  # Extra retries for prod (longer apply)
        prod_apply_ok = "FAIL" not in r

    status = "OK" if prod_apply_ok else "FAIL (prod apply did not complete — Deploy/Verify will fail without prod EC2/ECS)"
    return f"run_full_infra_pipeline: {status}\n" + "\n".join(lines)


@tool("Run resolve-aws-limits.py to diagnose VPC/EIP usage and optionally release unassociated EIPs. Call before dev/prod Terraform apply to free quota. Input: region (default us-east-1), release_eips (default True to release unassociated EIPs).")
def run_resolve_aws_limits(region: str = "us-east-1", release_eips: bool = True) -> str:
    """
    Runs resolve-aws-limits.py to free VPC/EIP quota before Terraform apply.
    Call this before terraform_apply for infra/envs/dev and infra/envs/prod when
    apply might fail with VpcLimitExceeded or AddressLimitExceeded.
    """
    scripts_dir = _get_scripts_dir()
    script = os.path.join(scripts_dir, "resolve-aws-limits.py")
    if not os.path.isfile(script):
        return f"Error: script not found: {script}"
    cmd = [sys.executable, script, "--region", region]
    if release_eips:
        cmd.append("--release-unassociated-eips")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=scripts_dir)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            return f"resolve-aws-limits FAIL (code {r.returncode})\n{err}\n{out}"
        return f"resolve-aws-limits OK\n{out}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@tool("Run remove-terraform-blockers.py to delete CloudTrail trails that cause conflicts. Call before dev/prod Terraform apply. Input: region (default us-east-1).")
def run_remove_terraform_blockers(region: str = "us-east-1") -> str:
    """
    Runs remove-terraform-blockers.py to delete CloudTrail trails.
    Call this before terraform_apply for dev/prod when apply might fail with
    ResourceAlreadyExistsException for CloudTrail.
    """
    scripts_dir = _get_scripts_dir()
    script = os.path.join(scripts_dir, "remove-terraform-blockers.py")
    if not os.path.isfile(script):
        return f"Error: script not found: {script}"
    cmd = [sys.executable, script, "--region", region]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=scripts_dir)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            return f"remove-terraform-blockers FAIL (code {r.returncode})\n{err}\n{out}"
        return f"remove-terraform-blockers OK\n{out}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def _parse_tfvars(work_dir: str, var_file: Optional[str]) -> dict:
    """Parse tfvars file into dict of key=value. Returns {} if file missing or unparseable."""
    if not var_file:
        return {}
    path = os.path.join(work_dir, var_file)
    if not os.path.isfile(path):
        return {}
    out = {}
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@tool("When terraform apply fails with EntityAlreadyExists for IAM Role: import existing ec2_role and codedeploy_role into state, then retry apply. Input: relative_path (e.g. infra/envs/prod), var_file (e.g. prod.tfvars). Only applies when enable_ecs=false (EC2 path).")
def run_import_platform_iam_on_conflict(relative_path: str, var_file: Optional[str] = None) -> str:
    """
    When terraform apply fails with EntityAlreadyExists for IAM Role, the IAM roles
    (ec2_role, codedeploy_role) exist in AWS but not in Terraform state. This tool
    imports them so a retry apply can succeed. Call after apply fails, then retry
    terraform_apply. Only runs when enable_ecs=false (EC2/ASG path).
    """
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    vars_d = _parse_tfvars(work_dir, var_file)
    project = vars_d.get("project", "bluegreen")
    env = vars_d.get("env") or ("prod" if "prod" in relative_path else "dev")
    enable_ecs = vars_d.get("enable_ecs", "false").lower() in ("true", "1", "yes")
    if enable_ecs:
        return "Skipped: enable_ecs=true (ECS path); ec2_role and codedeploy_role have count=0."
    ec2_role_name = f"{project}-{env}-ec2-role"
    codedeploy_role_name = f"{project}-{env}-codedeploy-role"
    imports = [
        ("module.platform.aws_iam_role.ec2_role[0]", ec2_role_name),
        ("module.platform.aws_iam_role.codedeploy_role[0]", codedeploy_role_name),
    ]
    # Terraform import needs -var-file to resolve required variables when loading config
    import_cmd_base = ["terraform", "import"]
    if var_file:
        var_path = os.path.abspath(os.path.join(work_dir, var_file))
        if os.path.isfile(var_path):
            import_cmd_base.extend(["-var-file", var_path])
    results = []
    for addr, rid in imports:
        try:
            cmd = import_cmd_base + [addr, rid]
            r = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                results.append(f"{addr}: imported OK")
            else:
                results.append(f"{addr}: {r.stderr or r.stdout or 'unknown'}")
        except FileNotFoundError:
            return "Error: terraform not found in PATH."
        except Exception as e:
            results.append(f"{addr}: {type(e).__name__}: {e}")
    return "import_platform_iam:\n" + "\n".join(results)


@tool("When terraform apply fails with ResourceAlreadyExistsException: import CloudWatch log groups, IAM policy, CodeDeploy app into state, then retry. Input: relative_path (e.g. infra/envs/prod), var_file (e.g. prod.tfvars).")
def run_import_existing_platform_resources(relative_path: str, var_file: Optional[str] = None) -> str:
    """
    When terraform apply fails with ResourceAlreadyExistsException (CloudWatch Log Group,
    IAM Policy, CodeDeploy Application), import the existing resources into Terraform state
    so a retry apply can succeed. Call after apply fails with ResourceAlreadyExistsException.
    """
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    vars_d = _parse_tfvars(work_dir, var_file)
    project = vars_d.get("project", "bluegreen")
    env = vars_d.get("env") or ("prod" if "prod" in relative_path else "dev")
    enable_ecs = vars_d.get("enable_ecs", "false").lower() in ("true", "1", "yes")

    # Terraform import needs -var-file to resolve required variables when loading config
    import_cmd_base = ["terraform", "import"]
    if var_file:
        var_path = os.path.abspath(os.path.join(work_dir, var_file))
        if os.path.isfile(var_path):
            import_cmd_base.extend(["-var-file", var_path])
    results = []
    # CloudWatch log groups: docker, system (always); ecs_app (only when enable_ecs=true)
    log_groups = [
        ("docker", f"/{project}/{env}/docker"),
        ("system", f"/{project}/{env}/system"),
    ]
    if enable_ecs:
        log_groups.append(("ecs_app[0]", f"/ecs/{project}-{env}-app"))
    for name, log_group in log_groups:
        addr = f"module.platform.aws_cloudwatch_log_group.{name}"
        try:
            cmd = import_cmd_base + [addr, log_group]
            r = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                results.append(f"{addr}: imported OK")
            else:
                err = (r.stderr or r.stdout or "").strip()
                if "does not exist" in err or "Cannot import" in err:
                    results.append(f"{addr}: skip (not found)")
                elif "already managed" in err:
                    results.append(f"{addr}: skip (already in state)")
                else:
                    results.append(f"{addr}: {err[:200]}")
        except FileNotFoundError:
            return "Error: terraform not found in PATH."
        except Exception as e:
            results.append(f"{addr}: {type(e).__name__}: {e}")

    # IAM policy and CodeDeploy app (only when enable_ecs=false)
    if not enable_ecs:
        policy_name = f"{project}-{env}-codedeploy-autoscaling"
        app_name = f"{project}-{env}-codedeploy-app"
        region = vars_d.get("region", "us-east-1")
        try:
            import boto3
            sts = boto3.client("sts", region_name=region)
            account = sts.get_caller_identity()["Account"]
            policy_arn = f"arn:aws:iam::{account}:policy/{policy_name}"
            for addr, rid in [
                ("module.platform.aws_iam_policy.codedeploy_autoscaling[0]", policy_arn),
                ("module.platform.aws_codedeploy_app.app[0]", app_name),
            ]:
                try:
                    cmd = import_cmd_base + [addr, rid]
                    r = subprocess.run(
                        cmd,
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if r.returncode == 0:
                        results.append(f"{addr}: imported OK")
                    else:
                        err = (r.stderr or r.stdout or "").strip()
                        if "does not exist" in err or "Cannot import" in err:
                            results.append(f"{addr}: skip (not found)")
                        else:
                            results.append(f"{addr}: {err[:200]}")
                except Exception as e:
                    results.append(f"{addr}: {type(e).__name__}: {e}")
        except Exception as e:
            results.append(f"boto3/STS: {type(e).__name__}: {e}")

    return "import_existing_platform_resources:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Build tools (used by Build Engineer agent)
# ---------------------------------------------------------------------------

@tool("Run 'docker build' for the app. Input: app_relative_path (default 'app'), tag (e.g. latest or a version). Uses APP_ROOT when set (e.g. crew-DevOps/app), else repo_root/app.")
def docker_build(app_relative_path: str = "app", tag: str = "latest") -> str:
    """
    "Build a Docker image from the app folder." Runs `docker build` in the
    app directory (either the one set by set_app_root or project/app). The image is
    tagged as app:tag (e.g. app:latest). That image is what gets pushed to ECR and
    deployed later.
    """
    # Get optional app path; if set, we build from there instead of project/app.
    app_root = get_app_root()
    # Get the project folder path.
    root = get_repo_root()
    # Use app_root if set, otherwise project_folder/app (or whatever app_relative_path is).
    work_dir = app_root if app_root else os.path.join(root, app_relative_path)
    # If that folder doesn't exist, return an error and stop.
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    try:
        # Run docker build in work_dir; tag the image as app:tag (e.g. app:latest); timeout 300 seconds.
        result = subprocess.run(
            ["docker", "build", "-t", f"app:{tag}", "."],
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        # If build succeeded, return OK and the tag.
        if result.returncode == 0:
            return f"docker build in {work_dir}: OK (tag app:{tag})"
        # Otherwise return FAIL and the build output.
        return f"docker build FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    # If docker is not installed, return a friendly message.
    except FileNotFoundError:
        return "Error: docker not found in PATH."
    # Any other error — return it.
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Push Docker image to ECR and update SSM image_tag. Input: ecr_repo_name (e.g. bluegreen-prod-app), image_tag (e.g. 202602081200), aws_region optional (default from env). Uses app:image_tag as local image; tags and pushes to ECR then puts SSM /bluegreen/prod/image_tag.")
def ecr_push_and_ssm(ecr_repo_name: str, image_tag: str, aws_region: Optional[str] = None) -> str:
    """
    "Push the image to AWS and tell the system which version to deploy."
    (1) Tags your local image (app:image_tag) with the full ECR address. (2) Logs Docker
    into ECR. (3) Pushes the image to ECR. (4) Writes the image_tag into AWS SSM at
    /bluegreen/prod/image_tag so Ansible knows "deploy this version." You
    need the ECR repo name (e.g. from read_ssm_parameter("/bluegreen/prod/ecr_repo_name")).
    """
    # Use the region passed in, or from the environment, or default us-east-1.
    region = aws_region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        # We need AWS SDK to get account ID and to write to SSM.
        import boto3
        # STS lets us ask AWS "who am I?" to get the account ID.
        sts = boto3.client("sts", region_name=region)
        account = sts.get_caller_identity()["Account"]
        # Build the full ECR image address (account.dkr.ecr.region.amazonaws.com/repo:tag).
        ecr_uri = f"{account}.dkr.ecr.{region}.amazonaws.com/{ecr_repo_name}:{image_tag}"
        # Tag the local image (app:image_tag) with the ECR URI so Docker knows where to push it.
        result = subprocess.run(
            ["docker", "tag", f"app:{image_tag}", ecr_uri],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return f"docker tag failed: {result.stderr}"
        # Get a one-time password from AWS so Docker can log in to ECR (allow 60s for slow networks).
        login = subprocess.run(
            ["aws", "ecr", "get-login-password", "--region", region],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if login.returncode != 0:
            return f"ECR login failed: {login.stderr}"
        # Run docker login, piping the password from the previous command into it.
        login_cmd = subprocess.Popen(
            ["docker", "login", "--username", "AWS", "--password-stdin",
             f"{account}.dkr.ecr.{region}.amazonaws.com"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out, err = login_cmd.communicate(input=login.stdout, timeout=30)
        if login_cmd.returncode != 0:
            return f"docker login failed: {err}"
        # Push the tagged image to ECR (can take a while for large images).
        push = subprocess.run(
            ["docker", "push", ecr_uri],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if push.returncode != 0:
            stderr = push.stderr or ""
            if "immutable" in stderr.lower() or "cannot be overwritten" in stderr.lower():
                return (
                    f"docker push failed: {stderr.strip()}\n"
                    "ECR tag immutability is enabled. Use a unique image tag (e.g. build-YYYYMMDDTHHMMSSZ). "
                    "Retry: docker_build with tag=<unique>, then ecr_push_and_ssm with that same tag."
                )
            return f"docker push failed: {stderr}"
        # Write the image tag to SSM so deploy tools know which version to pull.
        ssm_path = _ssm_path("prod", "image_tag")
        ssm = boto3.client("ssm", region_name=region)
        ssm.put_parameter(
            Name=ssm_path,
            Value=image_tag,
            Type="String",
            Overwrite=True,
        )
        return f"ECR push and SSM update OK: {ecr_uri}, {ssm_path} = {image_tag}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Read PRE_BUILT_IMAGE_TAG from environment. Returns the value if set, else empty. Use when docker_build fails to decide whether to call write_ssm_image_tag.")
def read_pre_built_image_tag() -> str:
    """Return PRE_BUILT_IMAGE_TAG from env if set (for Hugging Face Space when image was built via GitHub Actions)."""
    val = (os.environ.get("PRE_BUILT_IMAGE_TAG") or "").strip()
    if not val or val.lower() in ("unset", "initial"):
        return "PRE_BUILT_IMAGE_TAG: not set"
    return f"PRE_BUILT_IMAGE_TAG: {val}"


@tool("Write image_tag to SSM when Docker is unavailable (e.g. Hugging Face Space). Use when image was built elsewhere (GitHub Actions, local). Input: image_tag (e.g. abc123def456 or latest), region optional. No Docker required.")
def write_ssm_image_tag(image_tag: str, region: Optional[str] = None) -> str:
    """
    Write the image_tag to SSM at /{project}/prod/image_tag. Use when Docker is not
    available (e.g. Hugging Face Space) but the image was built and pushed via GitHub
    Actions or locally. Set PRE_BUILT_IMAGE_TAG in env to provide the tag, or call
    this tool with the tag from ecr_list_image_tags. Enables deploy to proceed.
    """
    tag = (image_tag or "").strip()
    if not tag:
        return "Error: image_tag is required."
    if tag.lower() in ("unset", "initial"):
        return f"Error: image_tag '{tag}' is invalid; use the actual tag from ECR (e.g. from GitHub Actions GITHUB_SHA)."
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=region)
        ssm_path = _ssm_path("prod", "image_tag")
        ssm.put_parameter(Name=ssm_path, Value=tag, Type="String", Overwrite=True)
        return f"SSM updated: {ssm_path} = {tag}. Deploy can now use this image."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:250]}"


@tool("List image tags in an ECR repository. Input: ecr_repo_name (e.g. bluegreen-prod-app), region optional. Use when Docker unavailable to discover tags from GitHub Actions or prior builds.")
def ecr_list_image_tags(ecr_repo_name: str, region: Optional[str] = None) -> str:
    """
    List image tags in the given ECR repository. No Docker required. Use when
    docker_build fails (e.g. Hugging Face Space) but images exist from GitHub Actions.
    Returns comma-separated tags; pick the latest and call write_ssm_image_tag.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        ecr = boto3.client("ecr", region_name=region)
        resp = ecr.describe_images(repositoryName=ecr_repo_name, maxResults=20)
        images = resp.get("imageDetails", [])
        tags = []
        for img in images:
            for t in img.get("imageTags", []) or []:
                tags.append(t)
        tags = sorted(set(tags), reverse=True)[:10]
        if not tags:
            return f"ECR {ecr_repo_name}: no images found. Build and push via GitHub Actions (.github/workflows/build-push.yml) or locally first."
        return f"ECR {ecr_repo_name} tags: {', '.join(tags)}. Use write_ssm_image_tag with one of these."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:250]}"


def _get_codebuild_log_tail(cb_client, build_id: str, region: str, project: str, max_lines: int = 40) -> str:
    """Fetch last lines of CodeBuild CloudWatch log for failed builds."""
    try:
        resp = cb_client.batch_get_builds(ids=[build_id])
        builds = resp.get("builds", [])
        if not builds:
            return ""
        logs_info = builds[0].get("logs", {})
        cw = logs_info.get("cloudWatchLogs", {})
        group = cw.get("groupName")
        stream = cw.get("streamName")
        if not group or not stream:
            return ""
        import boto3
        logs = boto3.client("logs", region_name=region)
        resp = logs.get_log_events(logGroupName=group, logStreamName=stream, limit=max_lines, startFromHead=False)
        events = resp.get("events", [])
        if not events:
            return ""
        lines = [e.get("message", "").rstrip() for e in reversed(events)]
        tail = "\n".join(lines[-max_lines:])
        return f"Last log lines:\n{tail}\n\n"
    except Exception:
        return ""


@tool("Build the app via AWS CodeBuild when Docker is unavailable. Zips app, uploads to S3, runs CodeBuild, updates SSM image_tag. Input: ecr_repo_name (e.g. bluegreen-prod-app), app_relative_path (default 'app'), region optional. Requires bootstrap applied (build_source_bucket, codebuild_project outputs).")
def codebuild_build_and_push(
    ecr_repo_name: str,
    app_relative_path: str = "app",
    region: Optional[str] = None,
) -> str:
    """
    When Docker is unavailable (e.g. Hugging Face Space), build the app using
    AWS CodeBuild. Zips the app directory, uploads to S3, starts CodeBuild,
    waits for completion, then updates SSM image_tag. Automatic fallback — no
    manual steps. Requires bootstrap Terraform applied (build_source_bucket,
    codebuild_project outputs).
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    root = get_repo_root()
    app_root = get_app_root()
    work_dir = app_root if app_root else os.path.join(root, app_relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: app directory not found: {work_dir}"
    dockerfile_path = os.path.join(work_dir, "Dockerfile")
    if not os.path.isfile(dockerfile_path):
        return f"Error: Dockerfile not found in {work_dir}. App must contain a Dockerfile for CodeBuild."

    try:
        import boto3
        # Get bootstrap outputs
        bootstrap_dir = os.path.join(root, "infra", "bootstrap")
        if not os.path.isdir(bootstrap_dir):
            return "Error: infra/bootstrap not found. Run Generate and Infra steps first."
        r = subprocess.run(
            ["terraform", "output", "-raw", "build_source_bucket"],
            cwd=bootstrap_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return f"Error: build_source_bucket not found in bootstrap. Run terraform apply in infra/bootstrap first. stderr: {(r.stderr or r.stdout or '')[:200]}"
        bucket = r.stdout.strip()
        r = subprocess.run(
            ["terraform", "output", "-raw", "codebuild_project"],
            cwd=bootstrap_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return f"Error: codebuild_project not found in bootstrap. stderr: {(r.stderr or r.stdout or '')[:200]}"
        project = r.stdout.strip()

        sts = boto3.client("sts", region_name=region)
        account = sts.get_caller_identity()["Account"]
        image_tag = f"codebuild-{int(time.time())}"

        # Zip app directory
        zip_path = os.path.join(tempfile.gettempdir(), f"app-{image_tag}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, filenames in os.walk(work_dir):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    arc = os.path.relpath(fp, work_dir)
                    zf.write(fp, arc)

        # Upload to S3
        s3 = boto3.client("s3", region_name=region)
        s3.upload_file(zip_path, bucket, "app.zip")
        try:
            os.remove(zip_path)
        except OSError:
            pass

        # Start CodeBuild (with automatic retry on failure)
        cb = boto3.client("codebuild", region_name=region)
        env_override = [
            {"name": "IMAGE_TAG", "value": image_tag, "type": "PLAINTEXT"},
            {"name": "ECR_REPO", "value": ecr_repo_name, "type": "PLAINTEXT"},
            {"name": "AWS_ACCOUNT_ID", "value": account, "type": "PLAINTEXT"},
            {"name": "AWS_REGION", "value": region, "type": "PLAINTEXT"},
        ]
        for attempt in range(2):  # Initial try + 1 automatic retry
            if attempt > 0:
                # Retry: re-upload zip (in case of S3 sync delay) and new build
                image_tag = f"codebuild-{int(time.time())}-retry{attempt}"
                env_override[0] = {"name": "IMAGE_TAG", "value": image_tag, "type": "PLAINTEXT"}
                zip_path = os.path.join(tempfile.gettempdir(), f"app-{image_tag}.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for dirpath, _, filenames in os.walk(work_dir):
                        for fn in filenames:
                            fp = os.path.join(dirpath, fn)
                            arc = os.path.relpath(fp, work_dir)
                            zf.write(fp, arc)
                s3.upload_file(zip_path, bucket, "app.zip")
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                time.sleep(3)  # Brief delay before retry
            resp = cb.start_build(projectName=project, environmentVariablesOverride=env_override)
            build_id = resp["build"]["id"]
            for _ in range(120):
                resp = cb.batch_get_builds(ids=[build_id])
                if not resp["builds"]:
                    break
                status = resp["builds"][0]["buildStatus"]
                if status == "SUCCEEDED":
                    ssm = boto3.client("ssm", region_name=region)
                    ssm_path = _ssm_path("prod", "image_tag")
                    ssm.put_parameter(Name=ssm_path, Value=image_tag, Type="String", Overwrite=True)
                    return f"CodeBuild OK. SSM {ssm_path} = {image_tag}. Deploy can proceed."
                if status in ("FAILED", "FAULT", "STOPPED", "TIMED_OUT"):
                    if attempt < 1:
                        break  # Exit poll loop to retry
                    time.sleep(2)
                    log_tail = _get_codebuild_log_tail(cb, build_id, region, project)
                    return f"CodeBuild FAILED: {status} (after retry).\n{log_tail}Full logs: /aws/codebuild/{project}"
                time.sleep(5)
            if attempt >= 1:
                return "CodeBuild timed out (10 min). Check AWS CodeBuild console."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:300]}"


@tool("Read a Terraform output value. Input: output_name (e.g. artifacts_bucket, https_url), relative_path (e.g. infra/envs/prod). Runs 'terraform output -raw <output_name>' in that directory. Use this to get ssm_bucket for run_ansible_deploy.")
def get_terraform_output(output_name: str, relative_path: str) -> str:
    """
    Read a single Terraform output from a Terraform directory (e.g. infra/envs/prod).
    Returns the raw value so the Deploy agent can get artifacts_bucket for Ansible without asking the user.
    If backend init is required, tries terraform init -backend-config=backend.hcl first (for infra/envs/*).
    """
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"

    def _run_output() -> tuple[int, str, str]:
        r = subprocess.run(
            ["terraform", "output", "-raw", output_name],
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        return r.returncode, r.stdout or "", r.stderr or ""

    try:
        code, out, err = _run_output()
        # If output fails and this is dev/prod, try init with backend.hcl (handles "Backend initialization required" and similar)
        if code != 0 and relative_path.startswith("infra/envs/"):
            backend_hcl = os.path.join(work_dir, "backend.hcl")
            if os.path.isfile(backend_hcl):
                with open(backend_hcl, "r", encoding="utf-8") as f:
                    backend_content = f.read()
                # If backend has placeholders, init will fail — give clear guidance
                if "YOUR_TFSTATE" in backend_content or "YOUR_TFLOCK" in backend_content:
                    return (
                        f"terraform output {output_name} in {relative_path}: FAIL — backend.hcl has placeholders (YOUR_TFSTATE_BUCKET, etc.). "
                        "Run the full infra pipeline with Allow Terraform apply checked so bootstrap applies and update_backend_from_bootstrap fills real values."
                    )
                init_r = subprocess.run(
                    ["terraform", "init", "-backend-config", "backend.hcl", "-reconfigure"],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                if init_r.returncode == 0:
                    code, out, err = _run_output()
                else:
                    init_err = (init_r.stderr or init_r.stdout or "").strip()
                    err = err or init_err
        if code != 0:
            err_msg = (err or out or "unknown error").strip()
            if "backend" in err_msg.lower() or "initialization" in err_msg.lower() or "YOUR_" in err_msg:
                return (
                    f"terraform output {output_name} in {relative_path}: FAIL — backend not initialized. "
                    "Ensure bootstrap was applied and update_backend_from_bootstrap ran. Re-run with Allow Terraform apply."
                )
            return f"terraform output {output_name} in {relative_path}: FAIL\nstderr: {err_msg[:500]}"
        if not (out and out.strip()):
            return f"terraform output {output_name} in {relative_path}: empty value"
        return f"terraform output {output_name} in {relative_path} = {out.strip()}"
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    except subprocess.TimeoutExpired:
        return f"Error: terraform output timed out in {relative_path}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


# ---------------------------------------------------------------------------
# Shared: SSM (used by Build, Deploy, and Verifier agents)
# ---------------------------------------------------------------------------

@tool("Read an AWS SSM Parameter Store value. Input: parameter name (e.g. /bluegreen/prod/image_tag), region optional.")
def read_ssm_parameter(name: str, region: Optional[str] = None) -> str:
    """
    "Read a value from AWS Parameter Store." SSM is like a small key-value
    store in AWS. We store things like the ECR repo name and the current image tag
    there. This tool fetches one value by name (e.g. /bluegreen/prod/image_tag). Used
    to get repo name for push, or to verify what tag is set after deploy.
    """
    # Use the region passed in, or from the environment, or default us-east-1.
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        # Use the AWS SDK to talk to Parameter Store.
        import boto3
        ssm = boto3.client("ssm", region_name=region)
        # Fetch the parameter by name; WithDecryption=True so we get the real value if it was encrypted.
        resp = ssm.get_parameter(Name=name, WithDecryption=True)
        value = resp["Parameter"]["Value"]
        return f"SSM {name} = {value}"
    except Exception as e:
        return f"SSM {name} error: {type(e).__name__}: {str(e)[:200]}"


@tool("Read SSM /{project}/prod/image_tag. Uses project from set_project (requirements.json). Region optional.")
def read_ssm_image_tag(region: Optional[str] = None) -> str:
    """
    Read the prod image_tag from SSM. Path is /{project}/prod/image_tag where project
    comes from requirements.json (set by flow). Use this instead of read_ssm_parameter
    to avoid path construction errors. Returns value or error.
    """
    try:
        path = _ssm_path("prod", "image_tag")
        return _call_tool(read_ssm_parameter, path, region)
    except Exception as e:
        return f"SSM read error: {type(e).__name__}: {str(e)[:300]}"


@tool("Read SSM /{project}/prod/ecr_repo_name. Uses project from set_project (requirements.json). Region optional.")
def read_ssm_ecr_repo_name(region: Optional[str] = None) -> str:
    """
    Read the prod ECR repo name from SSM. Path is /{project}/prod/ecr_repo_name where
    project comes from requirements.json (set by flow). Use this instead of
    read_ssm_parameter to avoid path construction errors. Returns value or error.
    """
    try:
        path = _ssm_path("prod", "ecr_repo_name")
        return _call_tool(read_ssm_parameter, path, region)
    except Exception as e:
        return f"SSM read error: {type(e).__name__}: {str(e)[:300]}"


# ---------------------------------------------------------------------------
# Deploy tools (used by Deploy Engineer agent; DEPLOY_METHOD chooses ansible, ssh_script, or ecs)
# ---------------------------------------------------------------------------

@tool("Run Ansible deploy playbook over SSM. Input: env (prod or dev), ssm_bucket (S3 bucket for SSM transfer, e.g. from terraform output artifacts_bucket), ansible_dir relative to repo (default ansible). Runs: ansible-playbook -i inventory/ec2_{env}.aws_ec2.yml playbooks/deploy.yml -e ssm_bucket=... -e env=...")
def run_ansible_deploy(env: str = "prod", ssm_bucket: str = "", ansible_dir: str = "ansible", region: Optional[str] = None) -> str:
    """
    "Deploy the app using Ansible." Runs the Ansible playbook that connects
    to your EC2 instances via SSM (no SSH), pulls the Docker image from ECR (using
    the tag from SSM), and runs the container. You must pass ssm_bucket (get it from
    terraform output -raw artifacts_bucket in infra/envs/prod). env is "prod" or "dev".
    """
    # Ansible needs the S3 bucket name for SSM; if missing, return a clear error.
    if not ssm_bucket:
        return "Error: ssm_bucket is required. Get it from terraform output -raw artifacts_bucket in infra/envs/prod (or dev)."
    # Get the project folder and the ansible subfolder (e.g. project/ansible).
    root = get_repo_root()
    work_dir = os.path.join(root, ansible_dir)
    if not os.path.isdir(work_dir):
        return f"Error: ansible directory not found: {work_dir}"
    # Inventory file name depends on env (e.g. inventory/ec2_prod.aws_ec2.yml).
    inv = f"inventory/ec2_{env}.aws_ec2.yml"
    inv_path = os.path.join(work_dir, inv)
    if not os.path.isfile(inv_path):
        return f"Error: inventory not found: {inv_path}"
    # Use the region passed in, or from the environment, or default.
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    # Build the ansible-playbook command with inventory, playbook, and extra vars.
    extra_vars = f"ssm_bucket={ssm_bucket} env={env} ssm_region={region}"
    # Optional wait so EC2 instances created by Terraform have time to reach "running" and get tags.
    wait_s = 0
    try:
        wait_s = int(os.environ.get("ANSIBLE_WAIT_BEFORE_DEPLOY", "0") or "0")
    except ValueError:
        pass
    if wait_s > 0:
        import time
        wait_s = min(wait_s, 300)  # cap at 5 minutes
        time.sleep(wait_s)
        # Note: no stdout here; tool output is returned to the agent. Wait has completed.
    # On Windows, Ansible CLI often fails with WinError 1; run playbook in WSL unless opted out.
    use_wsl = (sys.platform == "win32" and os.environ.get("ANSIBLE_USE_WSL", "1").strip().lower() not in ("0", "false", "no")) or (os.environ.get("ANSIBLE_USE_WSL", "").strip().lower() in ("1", "true", "yes"))
    if use_wsl:
        # On Windows, Ansible CLI can raise OSError [WinError 1] Incorrect function (Git Bash/MinGW).
        # Run the playbook inside WSL so Linux Ansible is used. Convert work_dir to WSL path.
        def _win_to_wsl_path(path: str) -> str:
            path = os.path.normpath(path)
            if len(path) >= 2 and path[1] == ":":
                drive = path[0].lower()
                rest = path[2:].replace("\\", "/").lstrip("/")
                return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
            return path.replace("\\", "/")
        wsl_work = _win_to_wsl_path(work_dir)
        # Pass AWS credentials into WSL so the dynamic inventory (aws_ec2) can list instances.
        def _bash_quote(v: str) -> str:
            if not v:
                return "''"
            return "'" + v.replace("'", "'\"'\"'") + "'"
        exports = []
        cred_hint = ""
        has_creds = any(os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"))
        if has_creds:
            for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                val = os.environ.get(key)
                if val:
                    exports.append(f"export {key}={_bash_quote(val)}")
        else:
            # Fallback: get credentials from AWS CLI (default profile / SSO) so WSL has them.
            cred_fallback_ok = False
            try:
                aws_cmd = ["aws", "configure", "export-credentials", "--format", "env-no-export"]
                if os.environ.get("AWS_PROFILE"):
                    aws_cmd.extend(["--profile", os.environ.get("AWS_PROFILE")])
                result = subprocess.run(
                    aws_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                if result.returncode == 0 and result.stdout:
                    for line in result.stdout.strip().splitlines():
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            key, _, val = line.partition("=")
                            key = key.strip()
                            val = (val.strip() or "").strip('"').strip("'")
                            if key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                                exports.append(f"export {key}={_bash_quote(val)}")
                                cred_fallback_ok = True
            except Exception:
                pass
            if not cred_fallback_ok:
                cred_hint = (
                    " No credentials were passed to WSL (env vars unset and 'aws configure export-credentials' failed or returned nothing). "
                    "Install AWS CLI v2, run 'aws configure' or 'aws sso login', then retry."
                )
        exports.append(f"export AWS_DEFAULT_REGION={_bash_quote(region)}")
        exports.append(f"export AWS_REGION={_bash_quote(region)}")
        export_str = " ".join(exports)
        # (1) Set ANSIBLE_PYTHON_INTERPRETER so the aws_ec2 inventory plugin uses the same Python we install boto3 for.
        # (2) Install boto3 with that interpreter. (3) Run ansible-playbook (plugin will use ANSIBLE_PYTHON_INTERPRETER).
        ensure_boto3 = (
            "export ANSIBLE_PYTHON_INTERPRETER=$(which python3 2>/dev/null || echo /usr/bin/python3); "
            '"$ANSIBLE_PYTHON_INTERPRETER" -m pip install -q --user boto3 2>/dev/null || true; '
        )
        cmd_str = (
            f"{export_str}; {ensure_boto3} cd {shlex.quote(wsl_work)} && ansible-playbook -i {shlex.quote(inv)} "
            f"playbooks/deploy.yml -e {shlex.quote(extra_vars)}"
        )
        try:
            result = subprocess.run(
                ["wsl", "bash", "-c", cmd_str],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            out = result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout
            if result.returncode == 0:
                if "no hosts matched" in (result.stdout or "").lower() or "skipping: no hosts matched" in (result.stdout or "").lower():
                    wait_note = f" (Waited {wait_s}s before deploy.)" if wait_s > 0 else ""
                    return (
                        f"Ansible deploy ({env}) via WSL: FAIL (no hosts matched)\n"
                        "Dynamic inventory found no EC2 instances. Check: 1) AWS credentials in WSL, "
                        "2) instances running and tagged Env=prod (prod) or Env=dev (dev), 3) region correct."
                        f"{wait_note} "
                        "If you just applied Terraform, try ANSIBLE_WAIT_BEFORE_DEPLOY=120 or run in WSL: ansible-inventory -i inventory/ec2_prod.aws_ec2.yml --list"
                        f"{cred_hint}\n"
                        f"stdout: {out}"
                    )
                return f"Ansible deploy ({env}) via WSL: OK\n{out}"
            # Detect WSL service unreachable or socket/buffer errors (Windows calling WSL).
            combined = (result.stdout or "") + (result.stderr or "")
            if "0x8007274c" in combined or "connected party did not properly respond" in combined.lower() or "connection attempt failed" in combined.lower():
                return (
                    f"Ansible deploy ({env}) via WSL: FAIL (WSL unreachable)\n"
                    "Windows could not connect to the WSL service (Error 0x8007274c). "
                    "Try: 1) Open a WSL terminal (e.g. 'wsl' or 'Ubuntu') so WSL is running. "
                    "2) Run 'wsl --shutdown' then open WSL again. "
                    "3) Restart the machine if WSL stays unresponsive. "
                    "4) Or run the playbook inside WSL manually: cd to the ansible dir, set AWS env, then ansible-playbook -i inventory/ec2_prod.aws_ec2.yml playbooks/deploy.yml -e ...\n"
                    f"stderr: {result.stderr}\nstdout: {result.stdout}"
                )
            if "0x80072747" in combined or "buffer space" in combined.lower() or "queue was full" in combined.lower():
                return (
                    f"Ansible deploy ({env}) via WSL: FAIL (WSL socket/buffer error 0x80072747)\n"
                    "Windows had a socket buffer or queue issue calling WSL. Try: 1) Set ANSIBLE_USE_WSL=0 in .env to run Ansible natively (may hit WinError 1 in some shells). "
                    "2) Run the pipeline from inside WSL (cd to Multi-Agent-Pipeline, then python run.py). "
                    "3) Restart WSL: wsl --shutdown, then open WSL again. "
                    "4) Use another deploy method: set DEPLOY_METHOD=ssh_script (with SSH key and EC2 reachable) or ecs if you have them.\n"
                    f"stderr: {result.stderr}\nstdout: {result.stdout}"
                )
            return f"Ansible deploy ({env}) via WSL: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
        except FileNotFoundError:
            return "Error: wsl not found. Install WSL and Ubuntu, or set ANSIBLE_USE_WSL=0 and run Ansible in WSL yourself. On Windows, native Ansible often fails with WinError 1."
        except Exception as e:
            err_str = str(e)
            if "0x8007274c" in err_str or "connection" in err_str.lower():
                return (
                    f"Ansible deploy ({env}) via WSL: FAIL (WSL unreachable)\n"
                    "Windows could not connect to the WSL service. Open a WSL terminal first, or run 'wsl --shutdown' then try again. "
                    f"Error: {type(e).__name__}: {err_str[:300]}"
                )
            if "0x80072747" in err_str or "buffer" in err_str.lower() or "queue" in err_str.lower():
                return (
                    f"Ansible deploy ({env}) via WSL: FAIL (WSL socket/buffer 0x80072747)\n"
                    "Set ANSIBLE_USE_WSL=0 to try native Ansible, or run the pipeline from inside WSL, or use DEPLOY_METHOD=ssh_script. "
                    f"Error: {type(e).__name__}: {err_str[:300]}"
                )
            return f"Error: {type(e).__name__}: {err_str[:200]}"
    # Non-Windows or ANSIBLE_USE_WSL=0: run ansible-playbook directly.
    cmd = [
        "ansible-playbook",
        "-i", inv,
        "playbooks/deploy.yml",
        "-e", extra_vars,
    ]
    try:
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        out = result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout
        if result.returncode == 0:
            if "no hosts matched" in (result.stdout or "").lower() or "skipping: no hosts matched" in (result.stdout or "").lower():
                return (
                    f"Ansible deploy ({env}): FAIL (no hosts matched)\n"
                    "Dynamic inventory found no EC2 instances. Check instance tags (Env=prod/dev) and region.\n"
                    f"stdout: {out}"
                )
            return f"Ansible deploy ({env}): OK\n{out}"
        return f"Ansible deploy ({env}): FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: ansible-playbook not found in PATH. Install Ansible and community.aws collection (ansible-galaxy collection install community.aws)."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:200]}"


# ---------------------------------------------------------------------------
# Deploy option 2: SSH script (no Ansible)
# ---------------------------------------------------------------------------

@tool("Deploy via SSH script (DEPLOY_METHOD=ssh_script). Input: env (prod or dev), region optional. Discovers EC2 instances by tag Env=<env>, SSHs to each and runs: read image from SSM, docker pull, restart container. Requires SSH_KEY_PATH or SSH_PRIVATE_KEY in env and instances reachable (e.g. bastion or public IP with port 22).")
def run_ssh_deploy(env: str = "prod", region: Optional[str] = None, ssh_user: str = "ec2-user", ssh_key_path: Optional[str] = None) -> str:
    """
    Deploy by SSHing to EC2 instances and running a small script: read image_tag and
    ecr_repo from SSM, docker pull, stop/rm existing container, docker run. Use when
    DEPLOY_METHOD=ssh_script. Set SSH_KEY_PATH (path to private key) or SSH_PRIVATE_KEY
    (key content) in .env. Instances must be reachable (SSH on port 22) and tagged Env=prod or Env=dev.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    key_path = ssh_key_path or os.environ.get("SSH_KEY_PATH")
    key_content = os.environ.get("SSH_PRIVATE_KEY")
    def _sanitize_bastion_host(s: str) -> str:
        if not s:
            return ""
        # Strip whitespace and CR/LF (Windows terraform output)
        s = s.replace("\r", "").replace("\n", "").strip()
        # Use only host part if value looks like "host:port"
        if ":" in s:
            host, port = s.rsplit(":", 1)
            if port.isdigit() and int(port) != 22:
                s = host.strip()
        return s

    bastion_host = _sanitize_bastion_host(os.environ.get("BASTION_HOST", ""))
    # If BASTION_HOST not set, try Terraform output (bastion IP can change on instance stop/start)
    if not bastion_host:
        tf_env = "infra/envs/prod" if env == "prod" else "infra/envs/dev"
        work_dir = os.path.join(get_repo_root(), tf_env)
        if os.path.isdir(work_dir):
            try:
                r = subprocess.run(
                    ["terraform", "output", "-raw", "bastion_public_ip"],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                if r.returncode == 0 and r.stdout:
                    bastion_host = _sanitize_bastion_host(r.stdout)
            except Exception:
                pass
    bastion_user = (os.environ.get("BASTION_USER") or "ec2-user").strip()
    if not key_path and not key_content:
        return (
            "Error: SSH deploy requires SSH_KEY_PATH (path to private key file) or "
            "SSH_PRIVATE_KEY (key content) in .env. Instances must be reachable on port 22."
        )
    try:
        import boto3
        ec2 = boto3.client("ec2", region_name=region)
        tag_val = "prod" if env == "prod" else "dev"
        r = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Env", "Values": [tag_val]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ],
        )
        addrs = []
        use_bastion = bool(bastion_host)
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                # Skip bastion host (do not run app deploy on it).
                name = ""
                for t in inst.get("Tags", []):
                    if t.get("Key") == "Name":
                        name = (t.get("Value") or "")
                        break
                if name and "bastion" in name.lower():
                    continue
                # When using bastion, use private IP so the bastion can reach the instance.
                if use_bastion:
                    ip = inst.get("PrivateIpAddress")
                else:
                    ip = inst.get("PublicIpAddress") or inst.get("PrivateIpAddress")
                if ip:
                    addrs.append(ip)
        if not addrs:
            return f"SSH deploy: no running EC2 instances found with tag Env={tag_val} in {region}. Apply Terraform and ensure instances are up."
        # Write key to temp file if passed as content (so ssh -i works)
        key_file = None
        known_hosts_path = None
        try:
            if key_content:
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                    f.write(key_content.replace("\\n", "\n"))
                    key_file = f.name
                os.chmod(key_file, 0o600)
                key_path = key_file
            # Resolve key path to absolute so SSH (including ProxyJump) finds it; use forward slashes for SSH
            if key_path and not key_content:
                key_path = os.path.abspath(key_path)
                if os.path.isfile(key_path):
                    key_path = key_path.replace("\\", "/")
            elif key_path and key_content:
                key_path = key_path.replace("\\", "/")
            # Empty known_hosts so we never prompt for new host keys in automation
            try:
                import tempfile
                kh = tempfile.NamedTemporaryFile(prefix="ssh_known_", delete=False)
                known_hosts_path = kh.name
                kh.close()
            except Exception:
                pass
            ssh_opts = [
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=15",
                "-o", "BatchMode=yes",
            ]
            if known_hosts_path:
                ssh_opts = ["-o", f"UserKnownHostsFile={known_hosts_path}"] + ssh_opts
            if key_path:
                ssh_opts.extend(["-i", key_path, "-o", "IdentitiesOnly=yes"])
            if bastion_host:
                # Use ProxyCommand with explicit -i so the bastion connection always gets the key (some SSH don't pass -i through ProxyJump)
                kh = (known_hosts_path or "/dev/null").replace("\\", "/")
                key_arg = f'"{key_path}"' if " " in key_path else key_path
                proxy_cmd = f'ssh -i {key_arg} -o StrictHostKeyChecking=no -o UserKnownHostsFile={kh} -W %h:%p -p 22 {bastion_user}@{bastion_host}'
                ssh_opts.extend(["-o", f"ProxyCommand={proxy_cmd}"])
            # Remote script: get image from SSM, ECR login, pull, stop/rm app container, run (sudo for Docker socket access)
            img_path = _ssm_path(tag_val, "image_tag")
            repo_path = _ssm_path(tag_val, "ecr_repo_name")
            script = (
                "set -e; "
                "export AWS_REGION=%s; "
                "IMAGE_TAG=$(aws ssm get-parameter --name %s --query Parameter.Value --output text 2>/dev/null || true); "
                "ECR_REPO=$(aws ssm get-parameter --name %s --query Parameter.Value --output text 2>/dev/null || true); "
                "if [ -z \"$IMAGE_TAG\" ] || [ -z \"$ECR_REPO\" ]; then echo MISSING_SSM; exit 1; fi; "
                "REGISTRY=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com; "
                "aws ecr get-login-password --region $AWS_REGION | sudo docker login --username AWS --password-stdin $REGISTRY; "
                "sudo docker pull $REGISTRY/$ECR_REPO:$IMAGE_TAG; "
                "sudo docker stop bluegreen-app 2>/dev/null || true; sudo docker rm -f bluegreen-app 2>/dev/null || true; "
                "sudo docker run -d --name bluegreen-app -p 8080:8080 --restart unless-stopped $REGISTRY/$ECR_REPO:$IMAGE_TAG"
            ) % (region, img_path, repo_path)
            out_lines = []
            for addr in addrs:
                cmd = ["ssh"] + ssh_opts + [f"{ssh_user}@{addr}", script]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                    if result.returncode == 0:
                        out_lines.append(f"{addr}: OK")
                    else:
                        # Show tail of stdout/stderr so real error (e.g. docker pull/run) is visible
                        so = result.stdout[-500:] if len(result.stdout) > 500 else result.stdout
                        se = result.stderr[-800:] if len(result.stderr) > 800 else result.stderr
                        out_lines.append(f"{addr}: FAIL stdout={so} stderr={se}")
                except Exception as e:
                    out_lines.append(f"{addr}: {type(e).__name__}: {str(e)[:150]}")
        finally:
            if key_file and os.path.isfile(key_file):
                try:
                    os.unlink(key_file)
                except Exception:
                    pass
            if known_hosts_path and os.path.isfile(known_hosts_path):
                try:
                    os.unlink(known_hosts_path)
                except Exception:
                    pass
        return "SSH deploy (" + env + "): " + "; ".join(out_lines)
    except Exception as e:
        return f"SSH deploy error: {type(e).__name__}: {str(e)[:250]}"


# ---------------------------------------------------------------------------
# Deploy option 4: ECS (update service with new image from SSM)
# ---------------------------------------------------------------------------

@tool("Deploy to ECS (DEPLOY_METHOD=ecs). Input: cluster_name, service_name, region optional. Reads image_tag and ecr_repo_name from SSM, updates ECS service task definition with new image and forces new deployment.")
def run_ecs_deploy(cluster_name: str, service_name: str, region: Optional[str] = None) -> str:
    """
    Deploy to ECS by updating the service with the image from SSM (/bluegreen/prod/image_tag and
    ecr_repo_name). Creates a new task definition revision with the new image URI and updates the
    service. Use when DEPLOY_METHOD=ecs. Get cluster_name and service_name from Terraform outputs
    (e.g. ecs_cluster_name, ecs_service_name) if your infra uses ECS.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        sts = boto3.client("sts", region_name=region)
        ssm = boto3.client("ssm", region_name=region)
        ecs = boto3.client("ecs", region_name=region)
        account = sts.get_caller_identity()["Account"]
        registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
        image_tag = ssm.get_parameter(Name=_ssm_path("prod", "image_tag"))["Parameter"]["Value"]
        if not image_tag or str(image_tag).lower() in ("unset", "initial"):
            return (
                f"ECS deploy blocked: SSM image_tag is '{image_tag or 'empty'}'. "
                "Build the image (docker_build + ecr_push_and_ssm) or use write_ssm_image_tag with a tag from ECR. "
                "On Hugging Face Space: run GitHub Actions build-push.yml first, then set PRE_BUILT_IMAGE_TAG or use ecr_list_image_tags + write_ssm_image_tag."
            )
        ecr_repo = ssm.get_parameter(Name=_ssm_path("prod", "ecr_repo_name"))["Parameter"]["Value"]
        image_uri = f"{registry}/{ecr_repo}:{image_tag}"
        # Get current task definition from service
        desc = ecs.describe_services(cluster=cluster_name, services=[service_name])
        if not desc.get("services"):
            return f"ECS deploy: service {service_name} not found in cluster {cluster_name}."
        svc = desc["services"][0]
        task_def_arn = svc.get("taskDefinition")
        if not task_def_arn:
            return f"ECS deploy: service {service_name} has no task definition."
        td = ecs.describe_task_definition(taskDefinition=task_def_arn)["taskDefinition"]
        container_name = td["containerDefinitions"][0]["name"]
        # Build params for register_task_definition (only accepted keys)
        allowed = {"family", "containerDefinitions", "networkMode", "volumes", "taskRoleArn", "executionRoleArn", "cpu", "memory", "requiresCompatibilities", "runtimePlatform"}
        reg_params = {k: v for k, v in td.items() if k in allowed and v is not None}
        # Deep copy containerDefs and update image for the main container
        reg_params["containerDefinitions"] = copy.deepcopy(td["containerDefinitions"])
        for c in reg_params["containerDefinitions"]:
            if c["name"] == container_name:
                c["image"] = image_uri
                break
        # Remove read-only fields from container defs if present
        for c in reg_params["containerDefinitions"]:
            for ro in ("containerArn", "taskArn", "networkInterfaces", "runtimeId"):
                c.pop(ro, None)
        reg = ecs.register_task_definition(**reg_params)
        new_task_def_arn = reg["taskDefinition"]["taskDefinitionArn"]
        ecs.update_service(cluster=cluster_name, service=service_name, taskDefinition=new_task_def_arn, forceNewDeployment=True)
        return f"ECS deploy: OK. Service {service_name} updated with {image_uri}; new deployment started."
    except Exception as e:
        return f"ECS deploy error: {type(e).__name__}: {str(e)[:250]}"


# ---------------------------------------------------------------------------
# Verify tools (used by Deployment Verifier agent)
# ---------------------------------------------------------------------------

@tool("Wait a number of seconds (e.g. for ECS task to become healthy). Input: seconds (integer, max 120). Use before http_health_check when deploy method was ECS.")
def wait_seconds(seconds: int) -> str:
    """Sleep for the given seconds. Used after ECS deploy so the new task has time to start and pass ALB health checks before verification."""
    s = max(0, min(int(seconds), 120))
    time.sleep(s)
    return f"Waited {s} seconds."


@tool("Check HTTP/HTTPS health of a URL. Input: full URL (e.g. https://app.example.com/health). Returns status code and OK or NOT OK.")
def http_health_check(url: str, timeout_seconds: int = 10) -> str:
    """
    "Check if this URL returns a healthy response." Does a GET request to the
    URL (e.g. https://app.example.com/health). If the status code is 200–299, we say
    OK; otherwise NOT OK. Used at the end of the pipeline to confirm the app is up
    after deploy.
    """
    # If no URL was given, return an error.
    if not url:
        return "Error: URL is empty."
    try:
        # Do a GET request; verify SSL certs; wait up to timeout_seconds.
        r = requests.get(url, verify=True, timeout=timeout_seconds)
        # Consider 2xx status codes as OK.
        ok = 200 <= r.status_code < 300
        return f"URL: {url} | Status: {r.status_code} | {'OK' if ok else 'NOT OK'}"
    except Exception as e:
        return f"URL: {url} | Error: {type(e).__name__}: {str(e)[:200]}"
