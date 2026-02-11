#!/usr/bin/env python3
"""
Run the Multi-Agent Deploy Pipeline: Terraform → Build → Deploy → Verify.

Usage:
  Set PROD_URL (and optionally AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY), then:
    python run.py
  Or: python run.py https://app.example.com

  REPO_ROOT: path to CICD-With-AI repo. When this folder is in crew-DevOps, default is crew-DevOps/CICD-With-AI.
  ALLOW_TERRAFORM_APPLY=1: allow Terraform apply (default: plan only).
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def main() -> int:
    prod_url = os.environ.get("PROD_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not prod_url:
        print("Usage: PROD_URL=https://app.example.com python run.py")
        print("   or: python run.py https://app.example.com")
        print("Optional: AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY=1")
        return 1

    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    parent_dir = os.path.dirname(_THIS_DIR)
    cicd_path = os.path.join(parent_dir, "CICD-With-AI")
    # Default REPO_ROOT: when in crew-DevOps, use CICD-With-AI next to this folder
    repo_root = os.environ.get("REPO_ROOT") or (cicd_path if os.path.isdir(cicd_path) else parent_dir)

    if not os.path.isdir(repo_root):
        print(f"REPO_ROOT not a directory: {repo_root}")
        return 1

    # When app is in crew-DevOps/app, use it for Docker build (Terraform still uses repo_root = CICD-With-AI)
    app_root = os.environ.get("APP_ROOT") or (os.path.join(parent_dir, "app") if os.path.isdir(os.path.join(parent_dir, "app")) else None)

    print(f"Repo root: {repo_root}")
    print(f"Prod URL:  {prod_url}")
    print(f"AWS region: {aws_region}")
    if app_root:
        print(f"App root:  {app_root}")
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        print("Terraform: plan only (set ALLOW_TERRAFORM_APPLY=1 to allow apply)")
    print()

    from flow import create_pipeline_crew
    crew = create_pipeline_crew(repo_root=repo_root, prod_url=prod_url, aws_region=aws_region, app_root=app_root)
    result = crew.kickoff()

    print()
    print("--- Pipeline result ---")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
