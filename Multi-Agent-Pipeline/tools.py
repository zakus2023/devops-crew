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
    # If the caller passed a var file (e.g. prod.tfvars), add it so Terraform gets variable values.
    if var_file:
        cmd.extend(["-var-file", var_file])
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
    # If the caller passed a var file, add it to the command.
    if var_file:
        cmd.extend(["-var-file", var_file])
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
    results = []
    for addr, rid in imports:
        try:
            r = subprocess.run(
                ["terraform", "import", addr, rid],
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
        ssm = boto3.client("ssm", region_name=region)
        ssm.put_parameter(
            Name="/bluegreen/prod/image_tag",
            Value=image_tag,
            Type="String",
            Overwrite=True,
        )
        return f"ECR push and SSM update OK: {ecr_uri}, /bluegreen/prod/image_tag = {image_tag}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


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
        if code != 0 and "Backend initialization required" in err and relative_path.startswith("infra/envs/"):
            backend_hcl = os.path.join(work_dir, "backend.hcl")
            if os.path.isfile(backend_hcl):
                subprocess.run(
                    ["terraform", "init", "-backend-config", "backend.hcl", "-reconfigure"],
                    cwd=work_dir,
                    capture_output=True,
                    timeout=90,
                )
                code, out, err = _run_output()
        if code != 0:
            return f"terraform output {output_name} in {relative_path}: FAIL\nstderr: {err or out}"
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
            script = (
                "set -e; "
                "export AWS_REGION=%s; "
                "IMAGE_TAG=$(aws ssm get-parameter --name /bluegreen/%s/image_tag --query Parameter.Value --output text 2>/dev/null || true); "
                "ECR_REPO=$(aws ssm get-parameter --name /bluegreen/%s/ecr_repo_name --query Parameter.Value --output text 2>/dev/null || true); "
                "if [ -z \"$IMAGE_TAG\" ] || [ -z \"$ECR_REPO\" ]; then echo MISSING_SSM; exit 1; fi; "
                "REGISTRY=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com; "
                "aws ecr get-login-password --region $AWS_REGION | sudo docker login --username AWS --password-stdin $REGISTRY; "
                "sudo docker pull $REGISTRY/$ECR_REPO:$IMAGE_TAG; "
                "sudo docker stop bluegreen-app 2>/dev/null || true; sudo docker rm -f bluegreen-app 2>/dev/null || true; "
                "sudo docker run -d --name bluegreen-app -p 8080:8080 --restart unless-stopped $REGISTRY/$ECR_REPO:$IMAGE_TAG"
            ) % (region, tag_val, tag_val)
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
        image_tag = ssm.get_parameter(Name="/bluegreen/prod/image_tag")["Parameter"]["Value"]
        ecr_repo = ssm.get_parameter(Name="/bluegreen/prod/ecr_repo_name")["Parameter"]["Value"]
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
