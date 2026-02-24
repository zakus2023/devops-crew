#!/usr/bin/env python3
"""
Destroy all infrastructure created by Combined-Crew (Terraform).

Runs `terraform destroy -auto-approve` in reverse order: prod → dev → bootstrap.
Bootstrap destruction removes the Terraform backend (S3 tfstate bucket + DynamoDB table).
Before bootstrap destroy, the backend bucket is emptied to ensure clean teardown.
Uses OUTPUT_DIR from .env or default ./output.

Usage:
  python destroy.py [--output-dir DIR] [--yes]
  python destroy.py -o test-ui/output -y
"""
import argparse
import os
import re
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def _run(cmd: list, cwd: str, timeout: int = 600) -> tuple[bool, str]:
    """Run command, return (success, stderr_or_stdout on failure)."""
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if r.returncode == 0:
            return True, ""
        return False, r.stderr or r.stdout or f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "terraform or aws CLI not found in PATH"
    except Exception as e:
        return False, str(e)


def _terraform_init(work_dir: str, backend_config: str | None) -> tuple[bool, str]:
    """Init Terraform in work_dir. Returns (success, error_message)."""
    cmd = ["terraform", "init", "-reconfigure"]
    if backend_config:
        cfg_path = os.path.join(work_dir, backend_config)
        if os.path.isfile(cfg_path):
            cmd.extend(["-backend-config", backend_config])
    ok, err = _run(cmd, work_dir, timeout=300)
    if not ok:
        print(f"  init failed: {err[:500]}")
        return False, err
    return True, ""


def _ensure_backend_from_bootstrap(output_dir: str) -> str | None:
    """Refresh dev/prod backend.hcl and tfvars from bootstrap outputs.

    Call before init'ing dev/prod so they use the correct S3 bucket. Returns None on
    success, or an error message if bootstrap outputs could not be read.
    """
    bootstrap_dir = os.path.join(output_dir, "infra", "bootstrap")
    if not os.path.isdir(bootstrap_dir):
        return None  # no bootstrap, skip
    ok, _ = _terraform_init(bootstrap_dir, None)
    if not ok:
        return "bootstrap init failed"

    def _output(name: str) -> str | None:
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
        if not val or "Warning" in val or "No outputs" in val or "\n" in val:
            return None
        if any(c in val for c in ("╷", "╵", "│", "\x1b")):
            return None
        if len(val) > 128 or not all(c.isalnum() or c in "-_.%" for c in val):
            return None
        return val

    tfstate_bucket = _output("tfstate_bucket")
    tflock_table = _output("tflock_table")
    cloudtrail_bucket = _output("cloudtrail_bucket")
    if not tfstate_bucket or not tflock_table:
        return "could not read tfstate_bucket or tflock_table from bootstrap"
    if not cloudtrail_bucket:
        return "could not read cloudtrail_bucket from bootstrap"

    for env in ("dev", "prod"):
        backend_path = os.path.join(output_dir, "infra", "envs", env, "backend.hcl")
        if os.path.isfile(backend_path):
            with open(backend_path, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(r'(\s*bucket\s*=\s*)"[^"]*"', f'\\1"{tfstate_bucket}"', content)
            content = re.sub(r'(\s*dynamodb_table\s*=\s*)"[^"]*"', f'\\1"{tflock_table}"', content)
            with open(backend_path, "w", encoding="utf-8") as f:
                f.write(content)
    tfvars_files = [("dev", "dev.tfvars"), ("prod", "prod.tfvars")]
    for env, fname in tfvars_files:
        path = os.path.join(output_dir, "infra", "envs", env, fname)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(
                r'(\s*cloudtrail_bucket\s*=\s*)"[^"]*"', f'\\1"{cloudtrail_bucket}"', content
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    return None


def _empty_backend_bucket(bootstrap_work_dir: str, region: str) -> None:
    """Empty the Terraform backend S3 bucket before destroying bootstrap.

    Dev/prod state files live in this bucket. Emptying it ensures bootstrap destroy
    can reliably delete the bucket (avoids versioning/force_destroy edge cases).
    """
    out = subprocess.run(
        ["terraform", "output", "-raw", "tfstate_bucket"],
        cwd=bootstrap_work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if out.returncode != 0 or not (bucket := (out.stdout or "").strip()):
        return
    print(f"  emptying backend bucket: {bucket}")
    subprocess.run(
        ["aws", "s3", "rm", f"s3://{bucket}/", "--recursive", "--region", region],
        capture_output=True,
        timeout=120,
    )


def _force_delete_ecr(work_dir: str, region: str, env: str) -> None:
    """Force-delete ECR repo. Get name from terraform output, or SSM fallback if state has no outputs."""
    ecr_name = None
    out = subprocess.run(
        ["terraform", "output", "-raw", "ecr_repo"],
        cwd=work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    ecr_name = (out.stdout or "").strip() if out.returncode == 0 else None
    # Fallback: state may have no outputs (e.g. "Warning: No outputs found"). Try SSM.
    if not ecr_name:
        ssm = subprocess.run(
            ["aws", "ssm", "get-parameter", "--name", f"/bluegreen/{env}/ecr_repo_name", "--query", "Parameter.Value", "--output", "text", "--region", region],
            capture_output=True,
            text=True,
            timeout=10,
        )
        ecr_name = (ssm.stdout or "").strip() if ssm.returncode == 0 else None
    if not ecr_name:
        return
    print(f"  force-deleting ECR repo: {ecr_name}")
    subprocess.run(
        ["aws", "ecr", "delete-repository", "--repository-name", ecr_name, "--force", "--region", region],
        capture_output=True,
        timeout=30,
    )


def run_destroy(
    output_dir: str,
    aws_region: str = "us-east-1",
    confirm: bool = True,
) -> tuple[bool, str]:
    """
    Tear down all infrastructure. Returns (success, message).
    confirm: if False, skips interactive prompt (for UI use).
    """
    output_dir = os.path.abspath(output_dir)
    lines = []
    if not os.path.isdir(output_dir):
        return False, (
            f"Output directory not found: {output_dir}\n"
            "Use the same output directory as your pipeline run (e.g. test-ui/output). "
            "Set via: UI textbox, OUTPUT_DIR in .env, or --output-dir when running destroy.py"
        )

    destroy_order = [
        ("infra/envs/prod", "prod.tfvars", "backend.hcl"),
        ("infra/envs/dev", "dev.tfvars", "backend.hcl"),
        ("infra/bootstrap", None, None),
    ]

    if confirm:
        lines.append(f"Output directory: {output_dir}")
        lines.append("Running terraform destroy -auto-approve in:")
        for path, var_file, _ in destroy_order:
            extra = f" (with -var-file={var_file})" if var_file else ""
            lines.append(f"  - {path}{extra}")
        lines.append("(Proceeding without interactive prompt)")

    # Refresh dev/prod backend.hcl from bootstrap outputs so init uses the correct bucket.
    err = _ensure_backend_from_bootstrap(output_dir)
    if err:
        lines.append(f"\nNote: {err}. Dev/prod backend.hcl may point to a non-existent bucket if bootstrap was already destroyed.")

    for relative_path, var_file, backend_config in destroy_order:
        work_dir = os.path.join(output_dir, relative_path)
        if not os.path.isdir(work_dir):
            lines.append(f"\nSkip (not a directory): {work_dir}")
            continue

        lines.append(f"\n--- {relative_path} ---")

        ok_init, init_err = _terraform_init(work_dir, backend_config)
        if not ok_init:
            lines.append("  Skipping destroy (init failed)")
            if backend_config and init_err and ("does not exist" in init_err or "404" in init_err):
                lines.append(
                    "  Hint: The S3 backend bucket may have been destroyed. Ensure you use the same"
                )
                lines.append(
                    "  output directory as the pipeline run, and that bootstrap has not been destroyed yet."
                )
            continue

        if var_file:
            env = "prod" if "prod" in relative_path else "dev"
            _force_delete_ecr(work_dir, aws_region, env)
        elif relative_path == "infra/bootstrap":
            _empty_backend_bucket(work_dir, aws_region)

        cmd = ["terraform", "destroy", "-auto-approve"]
        if var_file and os.path.isfile(os.path.join(work_dir, var_file)):
            cmd.extend(["-var-file", var_file])

        ok, err = _run(cmd, work_dir)
        if not ok:
            lines.append(f"  destroy failed: {err[:800]}")
            return False, "\n".join(lines)

    lines.append("\nDestroy complete.")
    return True, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tear down Combined-Crew infrastructure (terraform destroy)")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory (default: OUTPUT_DIR env or ./output)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    output_dir = (args.output_dir or os.environ.get("OUTPUT_DIR") or "").strip()
    if not output_dir:
        output_dir = os.path.join(_THIS_DIR, "output")
    output_dir = os.path.abspath(output_dir)
    region = os.environ.get("AWS_REGION", "us-east-1")

    destroy_order = [
        ("infra/envs/prod", "prod.tfvars", "backend.hcl"),
        ("infra/envs/dev", "dev.tfvars", "backend.hcl"),
        ("infra/bootstrap", None, None),
    ]
    if not args.yes:
        print(f"Output directory: {output_dir}")
        print("This will run 'terraform destroy -auto-approve' in:")
        for path, var_file, _ in destroy_order:
            extra = f" (with -var-file={var_file})" if var_file else ""
            print(f"  - {path}{extra}")
        try:
            answer = input("Proceed? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input).")
            return 0

    ok, msg = run_destroy(output_dir, aws_region=region, confirm=False)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
