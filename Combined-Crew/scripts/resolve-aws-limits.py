#!/usr/bin/env python3
"""
Diagnose and help resolve AWS VPC and EIP limits that block Terraform apply.

Terraform fails with VpcLimitExceeded or AddressLimitExceeded when:
- Too many VPCs (default 5 per region)
- Too many Elastic IPs (default 5 per region; each NAT gateway uses 1)

Each dev/prod env creates: 1 VPC, 1 NAT gateway → 1 EIP. So dev+prod need 2 VPCs and 2 EIPs minimum.

Usage:
  python scripts/resolve-aws-limits.py [--region us-east-1]
  python scripts/resolve-aws-limits.py --release-unassociated-eips   # release EIPs not attached to anything
  python scripts/resolve-aws-limits.py --list-vpcs                   # show VPCs (manual deletion required)
"""
import argparse
import json
import subprocess
import sys

_DEFAULT_REGION = "us-east-1"


def _run_aws(cmd: list, region: str) -> tuple[int, str, str]:
    full = ["aws", "--region", region, "--output", "json"] + cmd
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return -1, "", "aws CLI not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def list_vpcs(region: str) -> list[dict]:
    code, out, _ = _run_aws(["ec2", "describe-vpcs"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        return data.get("Vpcs", [])
    except json.JSONDecodeError:
        return []


def list_eips(region: str) -> tuple[list[dict], list[dict]]:
    code, out, _ = _run_aws(["ec2", "describe-addresses"], region)
    if code != 0:
        return [], []
    try:
        data = json.loads(out)
        addrs = data.get("Addresses", [])
        associated = [a for a in addrs if a.get("AssociationId")]
        unassociated = [a for a in addrs if not a.get("AssociationId")]
        return associated, unassociated
    except json.JSONDecodeError:
        return [], []


def release_eip(allocation_id: str, region: str) -> bool:
    code, _, err = _run_aws(["ec2", "release-address", "--allocation-id", allocation_id], region)
    return code == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose VPC/EIP limits; optionally release unassociated EIPs"
    )
    parser.add_argument("--region", "-r", default=_DEFAULT_REGION, help="AWS region")
    parser.add_argument(
        "--release-unassociated-eips",
        action="store_true",
        help="Release unassociated EIPs (frees quota for NAT gateways)",
    )
    parser.add_argument(
        "--list-vpcs",
        action="store_true",
        help="List VPCs with details (delete manually in console if needed)",
    )
    args = parser.parse_args()

    print(f"AWS Region: {args.region}")
    print("Default limits: 5 VPCs, 5 EIPs per region. Dev+prod need 2 VPCs and 2 EIPs (NAT gateways).")
    print()

    vpcs = list_vpcs(args.region)
    print(f"VPCs in region: {len(vpcs)}")
    if vpcs or args.list_vpcs:
        for v in vpcs:
            vpc_id = v.get("VpcId", "?")
            tags = {t["Key"]: t["Value"] for t in v.get("Tags", []) if t.get("Key") and t.get("Value")}
            name = tags.get("Name", "-")
            is_default = " (default)" if v.get("IsDefault") else ""
            print(f"  - {vpc_id}  Name={name}{is_default}")
    print()

    assoc, unassoc = list_eips(args.region)
    total = len(assoc) + len(unassoc)
    print(f"Elastic IPs: {total} total ({len(assoc)} associated, {len(unassoc)} unassociated)")
    if unassoc:
        for a in unassoc:
            print(f"  - {a.get('AllocationId')}  {a.get('PublicIp', '?')}  (unassociated)")
    print()

    if args.release_unassociated_eips:
        if not unassoc:
            print("No unassociated EIPs to release.")
            return 0
        print(f"Releasing {len(unassoc)} unassociated EIPs...")
        ok = all(release_eip(a["AllocationId"], args.region) for a in unassoc)
        if ok:
            print("Released successfully.")
        else:
            print("Some releases failed.", file=sys.stderr)
            return 1
        return 0

    # Diagnosis
    if len(vpcs) >= 5:
        print("WARNING: You have 5+ VPCs. Default limit is 5. Delete unused VPCs in AWS Console:")
        print("  EC2 → VPC → Your VPCs → select → Actions → Delete VPC")
        print("  (Delete subnets, IGW, NAT, etc. first if prompted)")
        print()
    if total >= 5:
        print("WARNING: You have 5+ EIPs. Default limit is 5. Release unassociated EIPs:")
        print("  python scripts/resolve-aws-limits.py --release-unassociated-eips --region", args.region)
        print("  Or: aws ec2 release-address --allocation-id <id>")
        print()

    print("Before Terraform apply, run (from project root):")
    print("  python Combined-Crew/scripts/remove-terraform-blockers.py --region", args.region)
    print("  python Combined-Crew/scripts/resolve-aws-limits.py --release-unassociated-eips --region", args.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
