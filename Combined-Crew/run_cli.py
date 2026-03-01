#!/usr/bin/env python3
"""
CLI entry point for running the pipeline in a subprocess.

Used by the Gradio UI to isolate the pipeline in a separate process so that when
it exits, the OS reclaims its memory (helps free tier 512MB on Render/HF).

Usage:
  python run_cli.py /path/to/job.json

Job JSON: requirements, output_dir, prod_url, aws_region, deploy_method,
  allow_terraform_apply, key_name, ssh_key_path, app_dir
SSH_PRIVATE_KEY: pass via env if using PEM content instead of path.
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
for _path in [
    os.path.join(_REPO_ROOT, "Full-Orchestrator"),
    os.path.join(_REPO_ROOT, "Multi-Agent-Pipeline"),
]:
    if _path not in sys.path:
        sys.path.append(_path)

def main() -> int:
    # Load .env AFTER reading the job file so env vars from .env do not override UI/job values.
    # Job values (deploy_method, etc.) are passed explicitly to run_crew and will be set into
    # os.environ there — so .env is only a fallback for vars not provided by the UI.
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_THIS_DIR, ".env"), override=False)
    except ImportError:
        pass
    if len(sys.argv) < 2:
        print("Usage: python run_cli.py /path/to/job.json", file=sys.stderr)
        return 1
    job_path = sys.argv[1]
    if not os.path.isfile(job_path):
        print(f"Job file not found: {job_path}", file=sys.stderr)
        return 1
    try:
        with open(job_path, "r", encoding="utf-8") as f:
            job = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid job JSON: {e}", file=sys.stderr)
        return 1

    requirements = job.get("requirements")
    if not requirements:
        print("Job must contain 'requirements' key", file=sys.stderr)
        return 1
    output_dir = job.get("output_dir", os.path.join(_THIS_DIR, "output"))
    prod_url = job.get("prod_url", "")
    aws_region = job.get("aws_region", "us-east-1")
    deploy_method = job.get("deploy_method", "ansible")
    allow_terraform_apply = job.get("allow_terraform_apply", False)
    key_name = job.get("key_name", "")
    ssh_key_path = job.get("ssh_key_path", "")
    app_dir = job.get("app_dir")
    ssh_key_content = os.environ.get("SSH_PRIVATE_KEY") or None

    from run import run_crew

    try:
        success, message = run_crew(
            requirements=requirements,
            output_dir=output_dir,
            prod_url=prod_url,
            aws_region=aws_region,
            deploy_method=deploy_method,
            allow_terraform_apply=allow_terraform_apply,
            key_name=key_name,
            ssh_key_path=ssh_key_path,
            ssh_key_content=ssh_key_content,
            app_dir=app_dir,
        )
        print(message)
        return 0 if success else 1
    except Exception as e:
        import traceback
        print(f"Error: {e}\n\n{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
