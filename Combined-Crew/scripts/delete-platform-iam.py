#!/usr/bin/env python3
"""
Delete platform IAM roles and instance profiles so Terraform can recreate them cleanly.

AWS requires: remove role from instance profile -> delete instance profile -> detach policies -> delete role.
If EC2 instances use the instance profile, disassociate it first.

Usage:
  python Combined-Crew/scripts/delete-platform-iam.py [--region us-east-1] [--project bluegreen] [--env dev] [--env prod]
  python Combined-Crew/scripts/delete-platform-iam.py --env dev --env prod   # delete both
  python Combined-Crew/scripts/delete-platform-iam.py --dry-run
"""
import argparse
import json
import subprocess
import sys

_DEFAULT_PROJECT = "bluegreen"
_DEFAULT_REGION = "us-east-1"


def _run_aws(cmd: list, region: str = None) -> tuple[int, str, str]:
    """Run aws CLI. For IAM, region is optional."""
    full = ["aws", "--output", "json"] + cmd
    if region:
        full = ["aws", "--region", region, "--output", "json"] + cmd
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return -1, "", "aws CLI not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _disassociate_instance_profile(association_id: str, region: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"    [dry-run] would disassociate instance profile: {association_id}")
        return True
    code, _, err = _run_aws(
        ["ec2", "disassociate-iam-instance-profile", "--association-id", association_id],
        region,
    )
    if code == 0:
        print(f"    disassociated: {association_id}")
        return True
    print(f"    failed disassociate {association_id}: {err}", file=sys.stderr)
    return False


def _remove_role_from_instance_profile(profile_name: str, role_name: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would remove role {role_name} from instance profile {profile_name}")
        return True
    code, _, err = _run_aws(
        [
            "iam",
            "remove-role-from-instance-profile",
            "--instance-profile-name", profile_name,
            "--role-name", role_name,
        ],
        None,
    )
    if code == 0:
        print(f"  removed role from instance profile: {profile_name}")
        return True
    if "NoSuchEntity" in err:
        print(f"  skip (not found): {profile_name}")
        return True
    print(f"  failed remove-role-from-instance-profile: {err}", file=sys.stderr)
    return False


def _delete_instance_profile(profile_name: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would delete instance profile: {profile_name}")
        return True
    code, _, err = _run_aws(["iam", "delete-instance-profile", "--instance-profile-name", profile_name], None)
    if code == 0:
        print(f"  deleted instance profile: {profile_name}")
        return True
    if "NoSuchEntity" in err:
        print(f"  skip (not found): {profile_name}")
        return True
    print(f"  failed delete instance profile: {err}", file=sys.stderr)
    return False


def _detach_and_delete_role(role_name: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would detach policies and delete role: {role_name}")
        return True
    # List attached managed policies
    code, out, err = _run_aws(["iam", "list-attached-role-policies", "--role-name", role_name], None)
    if code == 0:
        data = json.loads(out)
        for p in data.get("AttachedPolicies", []):
            arn = p["PolicyArn"]
            if arn.startswith("arn:aws:iam::aws:"):
                code2, _, _ = _run_aws(["iam", "detach-role-policy", "--role-name", role_name, "--policy-arn", arn], None)
                if code2 == 0:
                    print(f"    detached: {arn.split('/')[-1]}")
    # List inline policies
    code, out, err = _run_aws(["iam", "list-role-policies", "--role-name", role_name], None)
    if code == 0:
        data = json.loads(out)
        for name in data.get("PolicyNames", []):
            _run_aws(["iam", "delete-role-policy", "--role-name", role_name, "--policy-name", name], None)
    code, _, err = _run_aws(["iam", "delete-role", "--role-name", role_name], None)
    if code == 0:
        print(f"  deleted role: {role_name}")
        return True
    if "NoSuchEntity" in err:
        print(f"  skip (not found): {role_name}")
        return True
    print(f"  failed delete role: {err}", file=sys.stderr)
    return False


def _delete_ec2_role_and_profile(
    project: str, env: str, region: str, dry_run: bool
) -> bool:
    profile_name = f"{project}-{env}-ec2-profile"
    role_name = f"{project}-{env}-ec2-role"
    print(f"\n--- {env} EC2 role and instance profile ---")
    # 1. Disassociate instance profile from any EC2 instances
    code, out, _ = _run_aws(
        ["ec2", "describe-iam-instance-profile-associations", "--filters", "Name=instance-profile.name,Values=" + profile_name],
        region,
    )
    if code == 0:
        data = json.loads(out)
        assocs = data.get("IamInstanceProfileAssociations", [])
        for a in assocs:
            aid = a.get("AssociationId")
            if aid:
                _disassociate_instance_profile(aid, region, dry_run)
    # 2. Remove role from instance profile
    if not _remove_role_from_instance_profile(profile_name, role_name, dry_run):
        return False
    # 3. Delete instance profile
    if not _delete_instance_profile(profile_name, dry_run):
        return False
    # 4. Detach policies and delete role
    return _detach_and_delete_role(role_name, dry_run)


def _delete_codedeploy_role(project: str, env: str, dry_run: bool) -> bool:
    role_name = f"{project}-{env}-codedeploy-role"
    print(f"\n--- {env} CodeDeploy role ---")
    return _detach_and_delete_role(role_name, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete platform IAM roles and instance profiles (EC2 + CodeDeploy)"
    )
    parser.add_argument("--region", "-r", default=_DEFAULT_REGION, help="AWS region")
    parser.add_argument("--project", "-p", default=_DEFAULT_PROJECT, help="Project name")
    parser.add_argument("--env", "-e", action="append", default=[], help="Environment (dev, prod). Repeat for multiple.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done")
    args = parser.parse_args()
    envs = args.env if args.env else ["dev", "prod"]
    ok = True
    for env in envs:
        ok = _delete_ec2_role_and_profile(args.project, env, args.region, args.dry_run) and ok
        ok = _delete_codedeploy_role(args.project, env, args.dry_run) and ok
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
