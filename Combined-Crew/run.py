#!/usr/bin/env python3
"""
Run the Combined-Crew: Full-Orchestrator (generate from requirements) + Multi-Agent Pipeline (Terraform → Build → Deploy → Verify).

Usage:
  python run.py [--output-dir DIR] [--prod-url URL] [requirements.json]
  Or set REQUIREMENTS_JSON, OUTPUT_DIR, PROD_URL, AWS_REGION, ALLOW_TERRAFORM_APPLY in .env.

Flow: 1) Generate full project to output_dir. 2) Run Terraform (init/plan/apply). 3) Build & push to ECR, update SSM. 4) Deploy. 5) Verify (if PROD_URL set).
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)

# Allow importing from Full-Orchestrator and Multi-Agent-Pipeline
for _path in [
    _THIS_DIR,
    os.path.join(_REPO_ROOT, "Full-Orchestrator"),
    os.path.join(_REPO_ROOT, "Multi-Agent-Pipeline"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def load_requirements(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combined-Crew: generate from requirements then run Terraform → Build → Deploy → Verify"
    )
    parser.add_argument("requirements_file", nargs="?", default=None, help="Path to requirements.json")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for generated project (default: ./output)")
    parser.add_argument("--prod-url", "-p", default=None, help="Production URL for verify step (optional)")
    args = parser.parse_args()

    requirements_path = args.requirements_file or os.environ.get("REQUIREMENTS_JSON") or os.path.join(_THIS_DIR, "requirements.json")
    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR") or os.path.join(_THIS_DIR, "output")
    prod_url = args.prod_url or os.environ.get("PROD_URL", "")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    if not os.path.isfile(requirements_path):
        print(f"Requirements file not found: {requirements_path}")
        print("Create requirements.json or pass path. See .env.example.")
        return 1

    requirements = load_requirements(requirements_path)
    os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {os.path.abspath(output_dir)}")
    print(f"AWS region: {aws_region}")
    if prod_url:
        print(f"Prod URL (verify): {prod_url}")
    else:
        print("Prod URL: not set (verify step will skip health check)")
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        print("Terraform: plan only (set ALLOW_TERRAFORM_APPLY=1 to allow apply)")
    print()
    print("Starting Combined-Crew (Generate → Infra → Build → Deploy → Verify)...")
    print()

    from flow import create_combined_crew
    crew = create_combined_crew(output_dir=output_dir, requirements=requirements, prod_url=prod_url, aws_region=aws_region)
    result = crew.kickoff()

    print()
    print("--- Combined-Crew result ---")
    print(result)
    print()
    print(f"Generated project: {os.path.abspath(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
