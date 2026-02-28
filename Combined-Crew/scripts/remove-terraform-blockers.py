#!/usr/bin/env python3
"""
Remove AWS resources that block Terraform apply: CloudTrail trails and optionally unassociated EIPs.

- CloudTrail: Dev/prod each create a trail. If a previous run left trails, Terraform fails with
  ResourceAlreadyExistsException. This script deletes them so Terraform can recreate.
- Elastic IPs: AWS default limit is 5 per region. Unassociated EIPs block new NAT Gateways.
  Use --release-eips to release them (after reviewing with --dry-run).

Usage:
  python Combined-Crew/scripts/remove-terraform-blockers.py [--region us-east-1] [--project bluegreen]
  python Combined-Crew/scripts/remove-terraform-blockers.py --dry-run
  python Combined-Crew/scripts/remove-terraform-blockers.py --release-eips   # also release unassociated EIPs
"""
import argparse
import json
import subprocess
import sys

_DEFAULT_PROJECT = "bluegreen"
_DEFAULT_REGION = "us-east-1"


def _run_aws(cmd: list, region: str) -> tuple[int, str, str]:
    """Run aws CLI, return (returncode, stdout, stderr)."""
    full = ["aws", "--region", region, "--output", "json"] + cmd
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return -1, "", "aws CLI not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def delete_cloudtrail(name: str, region: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would delete trail: {name}")
        return True
    code, out, err = _run_aws(["cloudtrail", "delete-trail", "--name", name], region)
    if code == 0:
        print(f"  deleted trail: {name}")
        return True
    if "TrailNotFoundException" in err or "does not exist" in err.lower():
        print(f"  skip (not found): {name}")
        return True
    print(f"  failed {name}: {err or out}", file=sys.stderr)
    return False


def get_unassociated_eips(region: str) -> list[str]:
    """Return list of allocation IDs for unassociated EIPs."""
    code, out, _ = _run_aws(["ec2", "describe-addresses"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        addrs = data.get("Addresses", [])
        return [a["AllocationId"] for a in addrs if not a.get("AssociationId")]
    except (json.JSONDecodeError, KeyError):
        return []


def release_eip(allocation_id: str, region: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would release EIP: {allocation_id}")
        return True
    code, _, err = _run_aws(["ec2", "release-address", "--allocation-id", allocation_id], region)
    if code == 0:
        print(f"  released EIP: {allocation_id}")
        return True
    print(f"  failed {allocation_id}: {err}", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove CloudTrail trails and optionally release unassociated EIPs"
    )
    parser.add_argument("--region", "-r", default=_DEFAULT_REGION, help=f"AWS region")
    parser.add_argument("--project", "-p", default=_DEFAULT_PROJECT, help="Project name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--release-eips", action="store_true", help="Release unassociated EIPs")
    args = parser.parse_args()

    trails = [f"{args.project}-dev-trail", f"{args.project}-prod-trail"]
    print(f"CloudTrail trails to remove (region={args.region}):")
    for t in trails:
        print(f"  - {t}")

    if args.release_eips:
        eips = get_unassociated_eips(args.region)
        print(f"\nUnassociated Elastic IPs to release: {len(eips)}")
        for e in eips:
            print(f"  - {e}")
        if not eips:
            print("  (none)")

    if args.dry_run:
        print("\nDry run — no changes made.\n")
        for t in trails:
            delete_cloudtrail(t, args.region, dry_run=True)
        if args.release_eips:
            for e in get_unassociated_eips(args.region):
                release_eip(e, args.region, dry_run=True)
        return 0

    print("\nDeleting CloudTrail trails...")
    ok = all(delete_cloudtrail(t, args.region, dry_run=False) for t in trails)

    if args.release_eips:
        eips = get_unassociated_eips(args.region)
        if eips:
            print("\nReleasing unassociated EIPs...")
            ok = ok and all(release_eip(e, args.region, dry_run=False) for e in eips)
        else:
            print("\nNo unassociated EIPs to release.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
