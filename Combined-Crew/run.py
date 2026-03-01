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

# Combined-Crew must be first so "from flow" finds Combined-Crew/flow.py (not Full-Orchestrator or Multi-Agent-Pipeline)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
# Add Full-Orchestrator and Multi-Agent-Pipeline for cross-imports (append so they don't shadow Combined-Crew)
for _path in [
    os.path.join(_REPO_ROOT, "Full-Orchestrator"),
    os.path.join(_REPO_ROOT, "Multi-Agent-Pipeline"),
]:
    if _path not in sys.path:
        sys.path.append(_path)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def load_requirements(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _inject_deploy_method_into_requirements(requirements: dict, deploy_method: str) -> None:
    """
    Inject DEPLOY_METHOD-driven config into requirements so Generate produces correct tfvars.
    Matches Multi-Agent-Pipeline + Full-Orchestrator behavior.
    - DEPLOY_METHOD=ssh_script: enable_bastion=true, key_name from KEY_NAME env, enable_ecs=false.
    - DEPLOY_METHOD=ecs: enable_ecs=true.
    - ansible/default: enable_ecs=false.
    """
    prod = requirements.setdefault("prod", {})
    dev = requirements.setdefault("dev", {})

    if deploy_method == "ecs":
        prod["enable_ecs"] = True
        dev["enable_ecs"] = True
    else:
        prod["enable_ecs"] = False
        dev["enable_ecs"] = False

    if deploy_method == "ssh_script":
        key_name = (os.environ.get("KEY_NAME") or prod.get("key_name") or "").strip()
        # Placeholder or empty -> disable bastion to avoid InvalidKeyPair.NotFound
        placeholder = "YOUR_AWS_KEY_PAIR_NAME"
        if not key_name or key_name.lower() == placeholder.lower():
            prod["enable_bastion"] = False
            prod["key_name"] = ""
            print("Warning: DEPLOY_METHOD=ssh_script but KEY_NAME not set. Set KEY_NAME=your-aws-key-pair-name in .env for bastion. SSH_KEY_PATH also required. Bastion disabled to avoid InvalidKeyPair.NotFound.")
        else:
            prod["enable_bastion"] = True
            prod["key_name"] = key_name
            prod.setdefault("allowed_bastion_cidr", "0.0.0.0/0")


def _normalize_output_dir(output_dir: str, fallback: str) -> str:
    """Use fallback if output_dir looks like a Windows path on Linux (e.g. HF Space)."""
    out = (output_dir or "").strip()
    if not out:
        return fallback
    # On Linux/macOS, Windows paths (C:\, D:\, etc.) are invalid - use fallback
    if os.name != "nt" and len(out) >= 2 and out[1] == ":" and out[0].isalpha():
        return fallback
    return out


def run_crew(
    *,
    requirements: dict | str,
    output_dir: str,
    prod_url: str = "",
    aws_region: str = "us-east-1",
    deploy_method: str = "ansible",
    allow_terraform_apply: bool = False,
    key_name: str = "",
    ssh_key_path: str = "",
    ssh_key_content: str | None = None,
    app_dir: str | None = None,
) -> tuple[bool, str]:
    """
    Run the Combined-Crew from UI or programmatic call.
    Returns (success, message).
    requirements: dict or path to requirements.json.
    """
    fallback = os.path.join(_THIS_DIR, "output")
    output_dir = _normalize_output_dir(output_dir, fallback)
    _prev = {
        "DEPLOY_METHOD": os.environ.get("DEPLOY_METHOD"),
        "KEY_NAME": os.environ.get("KEY_NAME"),
        "SSH_KEY_PATH": os.environ.get("SSH_KEY_PATH"),
        "SSH_PRIVATE_KEY": os.environ.get("SSH_PRIVATE_KEY"),
        "ALLOW_TERRAFORM_APPLY": os.environ.get("ALLOW_TERRAFORM_APPLY"),
    }
    try:
        deploy_method = (deploy_method or "ansible").strip().lower()
        # Normalize invalid deploy methods (ecs_script->ecs, shs_script->ssh_script)
        if deploy_method == "ecs_script":
            deploy_method = "ecs"
        elif deploy_method == "shs_script":
            deploy_method = "ssh_script"
        elif deploy_method == "codedeploy":
            deploy_method = "ssh_script"  # CodeDeploy not used; fallback to SSH
        elif deploy_method not in ("ansible", "ssh_script", "ecs"):
            deploy_method = "ansible"
        os.environ["DEPLOY_METHOD"] = deploy_method
        if key_name:
            os.environ["KEY_NAME"] = key_name
        if ssh_key_path:
            os.environ["SSH_KEY_PATH"] = ssh_key_path
        if ssh_key_content:
            os.environ["SSH_PRIVATE_KEY"] = ssh_key_content
        os.environ["ALLOW_TERRAFORM_APPLY"] = "1" if allow_terraform_apply else "0"
        if isinstance(requirements, str):
            requirements = load_requirements(requirements)
        _inject_deploy_method_into_requirements(requirements, deploy_method)
        if os.path.isdir(output_dir):
            _sync_deploy_method_to_terraform(output_dir, deploy_method)
        os.makedirs(output_dir, exist_ok=True)
        from flow import create_combined_crew
        app_dir_resolved = (app_dir or "").strip() or None
        if app_dir_resolved and os.name != "nt" and len(app_dir_resolved) >= 2 and app_dir_resolved[1] == ":" and app_dir_resolved[0].isalpha():
            app_dir_resolved = None  # Windows path invalid on Linux
        if app_dir_resolved and (app_dir_resolved.startswith("http://") or app_dir_resolved.startswith("https://")):
            app_dir_resolved = None  # URL in app_dir — likely swapped with prod_url
        # prod_url must be HTTP(S) URL; reject file paths
        prod_url_clean = (prod_url or "").strip()
        if prod_url_clean and not (prod_url_clean.startswith("http://") or prod_url_clean.startswith("https://")):
            prod_url_clean = ""
        if prod_url_clean and len(prod_url_clean) >= 2 and prod_url_clean[1] == ":" and prod_url_clean[0].isalpha():
            prod_url_clean = ""  # Windows path
        crew = create_combined_crew(
            output_dir=output_dir,
            requirements=requirements,
            prod_url=prod_url_clean,
            aws_region=aws_region,
            app_dir=app_dir_resolved,
            deploy_method=deploy_method,
        )
        print(f"Output directory: {os.path.abspath(output_dir)}")
        print(f"Deploy method: {deploy_method}")
        print(f"AWS region: {aws_region}")
        print("Starting pipeline (Generate → Infra → Build → Deploy → Verify)...")
        print()
        result = crew.kickoff()
        print()
        print("--- Pipeline completed ---")
        out_path = os.path.abspath(output_dir)
        # Show shorter path when it's the default output dir (HF Space)
        if "Combined-Crew" in out_path and out_path.rstrip("/").endswith("output"):
            out_display = "./output"
        else:
            out_display = out_path
        return True, f"Completed successfully.\n\n--- Result ---\n{result}\n\nOutput: {out_display}"
    except Exception as e:
        import traceback
        return False, f"Error: {e}\n\n{traceback.format_exc()}"
    finally:
        for k, v in _prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _sync_deploy_method_to_terraform(output_dir: str, deploy_method: str) -> None:
    """
    Sync DEPLOY_METHOD to enable_ecs in existing tfvars (for output from previous runs).
    Matches Multi-Agent-Pipeline _sync_deploy_method_to_terraform.
    """
    import re
    enable_ecs = deploy_method == "ecs"
    value_str = "true" if enable_ecs else "false"
    for env_name, var_file in [("prod", "prod.tfvars"), ("dev", "dev.tfvars")]:
        path = os.path.join(output_dir, "infra", "envs", env_name, var_file)
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
    deploy_method = (os.environ.get("DEPLOY_METHOD") or "").strip().lower() or "ansible"
    _inject_deploy_method_into_requirements(requirements, deploy_method)
    if os.path.isdir(output_dir):
        _sync_deploy_method_to_terraform(output_dir, deploy_method)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {os.path.abspath(output_dir)}")
    print(f"Deploy method: {deploy_method} (from .env DEPLOY_METHOD)")
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
    crew = create_combined_crew(
        output_dir=output_dir,
        requirements=requirements,
        prod_url=prod_url,
        aws_region=aws_region,
        deploy_method=deploy_method,
    )
    result = crew.kickoff()

    print()
    print("--- Combined-Crew result ---")
    print(result)
    print()
    print(f"Generated project: {os.path.abspath(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
