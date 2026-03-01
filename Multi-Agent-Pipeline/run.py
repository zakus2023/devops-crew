#!/usr/bin/env python3
"""
Run the Multi-Agent Deploy Pipeline: Terraform → Build → Deploy → Verify.

Usage:
  Set PROD_URL (and optionally AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY), then:
    python run.py
  Or: python run.py https://app.example.com

  REPO_ROOT: path to deployment project (e.g. Full-Orchestrator/output). Default is parent of Multi-Agent-Pipeline if unset.
  ALLOW_TERRAFORM_APPLY=1: allow Terraform apply (default: plan only).
"""
import os
import re
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _normalize_path_for_platform(path: str) -> str:
    """On Linux (e.g. WSL), convert Windows paths like C:/My-Projects/... to /mnt/c/My-Projects/... so they exist."""
    if not path or sys.platform != "linux":
        return path
    # Windows drive path: C:/ or C:\ or D:/ etc.
    m = re.match(r"^([a-zA-Z]):[/\\](.*)$", path.strip())
    if m:
        drive, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
        return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
    return path
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def _sync_deploy_method_to_terraform(repo_root: str, deploy_method: str) -> None:
    """
    Sync .env DEPLOY_METHOD to Terraform enable_ecs in prod and dev tfvars. Runs before the crew.
    - DEPLOY_METHOD=ecs -> enable_ecs = true (ECS path only; no EC2 ASG or bastion).
    - Any other method (ssh_script, ansible) -> enable_ecs = false (EC2 path).
    The Infra task then runs terraform init/plan/apply for bootstrap, dev, prod (no manual apply needed).
    """
    enable_ecs = deploy_method == "ecs"
    value_str = "true" if enable_ecs else "false"
    for env_name, var_file in [("prod", "prod.tfvars"), ("dev", "dev.tfvars")]:
        path = os.path.join(repo_root, "infra", "envs", env_name, var_file)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if "enable_ecs" in content:
                new_content = re.sub(
                    r"enable_ecs\s*=\s*(?:true|false)",
                    f"enable_ecs = {value_str}",
                    content,
                    flags=re.IGNORECASE,
                )
            else:
                new_content = content.rstrip() + f"\nenable_ecs = {value_str}\n"
            if new_content != content:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Synced DEPLOY_METHOD={deploy_method} -> enable_ecs = {value_str} in infra/envs/{env_name}/{var_file}")
        except OSError:
            pass


def _get_prod_url_from_terraform(repo_root: str) -> str | None:
    """If prod Terraform has been applied, run 'terraform output -raw https_url' and return it; else None."""
    prod_dir = os.path.join(repo_root, "infra", "envs", "prod")
    if not os.path.isdir(prod_dir):
        return None
    try:
        r = subprocess.run(
            ["terraform", "output", "-raw", "https_url"],
            cwd=prod_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def main() -> int:
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    parent_dir = os.path.dirname(_THIS_DIR)
    # Default REPO_ROOT: parent of Multi-Agent-Pipeline (e.g. crew-DevOps). Set to your deployment project (e.g. Full-Orchestrator/output).
    repo_root = _normalize_path_for_platform(os.environ.get("REPO_ROOT") or parent_dir)

    if not os.path.isdir(repo_root):
        print(f"REPO_ROOT not a directory: {repo_root}")
        return 1

    # Option A: try to get prod URL from Terraform output (REPO_ROOT/infra/envs/prod).
    prod_url = _get_prod_url_from_terraform(repo_root)
    if prod_url:
        print(f"Prod URL (from terraform output): {prod_url}")
    # Option B: if Option A not available, use PROD_URL from .env or command line.
    if not prod_url:
        prod_url = os.environ.get("PROD_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not prod_url:
        print("Usage: PROD_URL=https://app.example.com python run.py")
        print("   or: python run.py https://app.example.com")
        print("   or: set REPO_ROOT to your deployment project and apply prod Terraform; run.py will read https_url from terraform output.")
        print("Optional: AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY=1")
        return 1

    # When app is in crew-DevOps/app, use it for Docker build (Terraform and Ansible still use repo_root)
    app_root = os.environ.get("APP_ROOT")
    if app_root is not None:
        app_root = _normalize_path_for_platform(app_root)
    else:
        app_root = (os.path.join(parent_dir, "app") if os.path.isdir(os.path.join(parent_dir, "app")) else None)

    deploy_method = (os.environ.get("DEPLOY_METHOD") or "").strip().lower() or "ansible"
    _sync_deploy_method_to_terraform(repo_root, deploy_method)
    print(f"Repo root: {repo_root}")
    print(f"Prod URL:  {prod_url}")
    print(f"AWS region: {aws_region}")
    print(f"Deploy method: {deploy_method} (from .env DEPLOY_METHOD)")
    if app_root:
        print(f"App root:  {app_root}")
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        print("Terraform: plan only (set ALLOW_TERRAFORM_APPLY=1 to allow apply)")
    else:
        print("Terraform: apply enabled — Infra task will run init/plan/apply for bootstrap, dev, and prod (no manual apply needed).")
    print()

    try:
        from flow import create_pipeline_crew
    except ModuleNotFoundError as e:
        if "crewai" in str(e).lower():
            print("Missing dependency: crewai not installed for this Python.")
            print("Install with the same interpreter you use to run: python -m pip install -r requirements.txt")
            return 1
        raise
    crew = create_pipeline_crew(repo_root=repo_root, prod_url=prod_url, aws_region=aws_region, app_root=app_root)
    result = crew.kickoff()

    print()
    print("--- Pipeline result ---")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
