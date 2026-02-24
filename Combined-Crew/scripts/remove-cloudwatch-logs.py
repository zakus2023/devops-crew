#!/usr/bin/env python3
"""
Remove CloudWatch log groups that cause Terraform ResourceAlreadyExistsException.

These log groups are created by the platform module (dev/prod). If they already exist
from a previous run or manual creation, Terraform apply fails. Run this script before
re-running Terraform apply to clean them up.

Usage:
  python scripts/remove-cloudwatch-logs.py [--region us-east-1] [--project bluegreen]
  python scripts/remove-cloudwatch-logs.py --dry-run   # show what would be deleted
"""
import argparse
import subprocess
import sys

_DEFAULT_PROJECT = "bluegreen"
_DEFAULT_REGION = "us-east-1"


def get_log_groups(project: str) -> list[str]:
    """Log group names used by the platform module for dev and prod."""
    return [
        f"/{project}/dev/docker",
        f"/{project}/dev/system",
        f"/ecs/{project}-dev-app",
        f"/{project}/prod/docker",
        f"/{project}/prod/system",
        f"/ecs/{project}-prod-app",
    ]


def delete_log_group(name: str, region: str, dry_run: bool) -> bool:
    """Delete a CloudWatch log group. Returns True if deleted or dry-run."""
    if dry_run:
        print(f"  [dry-run] would delete: {name}")
        return True
    try:
        r = subprocess.run(
            ["aws", "logs", "delete-log-group", "--log-group-name", name, "--region", region],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            print(f"  deleted: {name}")
            return True
        if "ResourceNotFoundException" in (r.stderr or ""):
            print(f"  skip (not found): {name}")
            return True
        print(f"  failed {name}: {r.stderr or r.stdout or r.returncode}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("  Error: aws CLI not found. Install AWS CLI and retry.", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove CloudWatch log groups that block Terraform apply"
    )
    parser.add_argument(
        "--region", "-r",
        default=_DEFAULT_REGION,
        help=f"AWS region (default: {_DEFAULT_REGION})",
    )
    parser.add_argument(
        "--project", "-p",
        default=_DEFAULT_PROJECT,
        help=f"Project name from requirements (default: {_DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    args = parser.parse_args()

    groups = get_log_groups(args.project)
    print(f"CloudWatch log groups to remove (region={args.region}):")
    for g in groups:
        print(f"  - {g}")
    if args.dry_run:
        print("\nDry run — no changes made.\n")
        for g in groups:
            delete_log_group(g, args.region, dry_run=True)
        return 0

    print("\nDeleting...")
    ok = all(delete_log_group(g, args.region, dry_run=False) for g in groups)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
