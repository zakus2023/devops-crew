#!/usr/bin/env python3
"""
Destroy infrastructure created by the Multi-Agent Pipeline (Terraform).

Runs `terraform destroy -auto-approve` in reverse order: prod → dev → bootstrap.
Uses the same REPO_ROOT as run.py (deployment project, e.g. Full-Orchestrator/output).

Usage:
  python destroy.py              # prompt for confirmation
  python destroy.py --yes       # destroy without prompting
"""
import os
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def main() -> int:
    parent_dir = os.path.dirname(_THIS_DIR)
    repo_root = os.environ.get("REPO_ROOT") or parent_dir

    if not os.path.isdir(repo_root):
        print(f"REPO_ROOT not a directory: {repo_root}")
        return 1

    destroy_order = [
        ("infra/envs/prod", "prod.tfvars"),
        ("infra/envs/dev", "dev.tfvars"),
        ("infra/bootstrap", None),
    ]

    if "--yes" not in sys.argv and "-y" not in sys.argv:
        print(f"Repo root: {repo_root}")
        print("This will run 'terraform destroy -auto-approve' in:")
        for path, var_file in destroy_order:
            print(f"  - {path}" + (f" (with -var-file={var_file})" if var_file else ""))
        try:
            answer = input("Proceed? [y/N]: ").strip().lower()
            if answer != "y" and answer != "yes":
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input).")
            return 0

    region = os.environ.get("AWS_REGION", "us-east-1")

    for relative_path, var_file in destroy_order:
        work_dir = os.path.join(repo_root, relative_path)
        if not os.path.isdir(work_dir):
            print(f"Skip (not a directory): {work_dir}")
            continue
        # Before destroying prod, force-delete ECR repo so Terraform can remove it (ECR fails if repo has images).
        if relative_path == "infra/envs/prod":
            out = subprocess.run(
                ["terraform", "output", "-raw", "ecr_repo"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0 and out.stdout and out.stdout.strip():
                ecr_name = out.stdout.strip()
                print(f"\n--- force-delete ECR repo {ecr_name} (so destroy can remove it) ---")
                subprocess.run(
                    ["aws", "ecr", "delete-repository", "--repository-name", ecr_name, "--force", "--region", region],
                    capture_output=True,
                    timeout=30,
                )
        cmd = ["terraform", "destroy", "-auto-approve"]
        if var_file and os.path.isfile(os.path.join(work_dir, var_file)):
            cmd.extend(["-var-file", var_file])
        print(f"\n--- terraform destroy in {relative_path} ---")
        result = subprocess.run(cmd, cwd=work_dir)
        if result.returncode != 0:
            print(f"terraform destroy in {relative_path} failed (exit {result.returncode})")
            return result.returncode

    print("\nDestroy complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
