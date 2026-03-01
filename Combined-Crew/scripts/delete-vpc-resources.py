#!/usr/bin/env python3
"""
Delete non-default VPC resources: NAT gateways, Internet gateways, subnets,
custom route tables, and the VPC itself. Skips the default VPC and its resources.

Deletion order: NAT Gateway → Load Balancers → EC2 (if --terminate-instances) → IGW → Subnets → Route Tables → VPC Endpoints → Security Groups → VPC

Use --terminate-instances to terminate EC2 instances (required if instances exist).

Usage:
  python Combined-Crew/scripts/delete-vpc-resources.py [--region us-east-1]
  python Combined-Crew/scripts/delete-vpc-resources.py --vpc-id vpc-xxx -y
  python Combined-Crew/scripts/delete-vpc-resources.py --prefix bluegreen --dry-run

Options:
  -y, --yes       Skip confirmation prompt
  -r, --region    AWS region (default: us-east-1)
  --vpc-id ID     Delete only this VPC (must be non-default)
  --prefix PREFIX Only delete VPCs whose Name tag starts with PREFIX
  --terminate-instances  Terminate EC2 instances in the VPC (required if instances exist)
  --dry-run       Show what would be deleted, no changes
"""
import argparse
import json
import subprocess
import sys
import time

_DEFAULT_REGION = "us-east-1"


def _run_aws(cmd: list, region: str, timeout: int = 60) -> tuple[int, str, str]:
    full = ["aws", "--region", region, "--output", "json"] + cmd
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return -1, "", "aws CLI not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _get_tag(v: dict, key: str) -> str:
    for t in v.get("Tags", []):
        if t.get("Key") == key:
            return t.get("Value", "") or ""
    return ""


def list_non_default_vpcs(region: str, prefix: str | None = None) -> list[dict]:
    code, out, _ = _run_aws(["ec2", "describe-vpcs"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        vpcs = [v for v in data.get("Vpcs", []) if not v.get("IsDefault")]
        if prefix:
            vpcs = [v for v in vpcs if _get_tag(v, "Name").startswith(prefix)]
        return vpcs
    except json.JSONDecodeError:
        return []


def delete_nat_gateways(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    code, out, _ = _run_aws(
        ["ec2", "describe-nat-gateways", "--filter", f"Name=vpc-id,Values={vpc_id}", "Name=state,Values=available,pending"],
        region,
    )
    if code != 0:
        return []
    try:
        data = json.loads(out)
        nats = data.get("NatGateways", [])
    except json.JSONDecodeError:
        return []
    deleted = []
    for nat in nats:
        nat_id = nat.get("NatGatewayId")
        if not nat_id:
            continue
        if dry_run:
            print(f"  [dry-run] would delete NAT gateway: {nat_id}")
            deleted.append(nat_id)
            continue
        code2, _, err = _run_aws(["ec2", "delete-nat-gateway", "--nat-gateway-id", nat_id], region)
        if code2 == 0:
            print(f"  deleted NAT gateway: {nat_id}")
            deleted.append(nat_id)
        else:
            print(f"  failed NAT gateway {nat_id}: {err.strip()[:120]}", file=sys.stderr)
    return deleted


def wait_nat_deleted(nat_id: str, region: str, max_wait: int = 120) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < max_wait:
        code, out, _ = _run_aws(["ec2", "describe-nat-gateways", "--nat-gateway-ids", nat_id], region)
        if code != 0:
            return False
        try:
            data = json.loads(out)
            nats = data.get("NatGateways", [])
            if not nats:
                return True
            state = nats[0].get("State", "")
            if state == "deleted":
                return True
        except json.JSONDecodeError:
            pass
        time.sleep(5)
    return False


def delete_load_balancers(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    """Delete ALB and NLB load balancers in the VPC."""
    code, out, _ = _run_aws(["elbv2", "describe-load-balancers"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        balancers = [lb for lb in data.get("LoadBalancers", []) if lb.get("VpcId") == vpc_id]
    except json.JSONDecodeError:
        return []
    deleted = []
    for lb in balancers:
        lb_arn = lb.get("LoadBalancerArn")
        lb_name = lb.get("LoadBalancerName", "")
        if not lb_arn:
            continue
        if dry_run:
            print(f"  [dry-run] would delete load balancer: {lb_name}")
            deleted.append(lb_arn)
            continue
        code2, _, err = _run_aws(["elbv2", "delete-load-balancer", "--load-balancer-arn", lb_arn], region)
        if code2 == 0:
            print(f"  deleted load balancer: {lb_name}")
            deleted.append(lb_arn)
        else:
            print(f"  failed load balancer {lb_name}: {err.strip()[:120]}", file=sys.stderr)
    return deleted


def _terminate_instances_in_vpc(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    """Terminate all EC2 instances in the VPC."""
    code, out, _ = _run_aws(
        ["ec2", "describe-instances", "--filters", f"Name=vpc-id,Values={vpc_id}", "Name=instance-state-name,Values=pending,running,stopping,stopped"],
        region,
    )
    if code != 0:
        return []
    try:
        data = json.loads(out)
        instances = []
        for r in data.get("Reservations", []):
            instances.extend(r.get("Instances", []))
    except json.JSONDecodeError:
        return []
    terminated = []
    ids = [i["InstanceId"] for i in instances if i.get("InstanceId")]
    if not ids:
        return []
    if dry_run:
        for iid in ids:
            print(f"  [dry-run] would terminate instance: {iid}")
        return ids
    code2, _, err = _run_aws(["ec2", "terminate-instances", "--instance-ids"] + ids, region)
    if code2 == 0:
        print(f"  terminating {len(ids)} instance(s)...")
        terminated = ids
    else:
        print(f"  failed terminate instances: {err.strip()[:120]}", file=sys.stderr)
    return terminated


def detach_and_delete_igw(vpc_id: str, region: str, dry_run: bool) -> bool:
    code, out, _ = _run_aws(
        ["ec2", "describe-internet-gateways", "--filters", f"Name=attachment.vpc-id,Values={vpc_id}"],
        region,
    )
    if code != 0:
        return True
    try:
        data = json.loads(out)
        igws = data.get("InternetGateways", [])
    except json.JSONDecodeError:
        return True
    for igw in igws:
        igw_id = igw.get("InternetGatewayId")
        if not igw_id:
            continue
        if dry_run:
            print(f"  [dry-run] would detach and delete IGW: {igw_id}")
            return True
        _run_aws(["ec2", "detach-internet-gateway", "--internet-gateway-id", igw_id, "--vpc-id", vpc_id], region)
        code2, _, err = _run_aws(["ec2", "delete-internet-gateway", "--internet-gateway-id", igw_id], region)
        if code2 == 0:
            print(f"  deleted IGW: {igw_id}")
        else:
            print(f"  failed IGW {igw_id}: {err.strip()[:120]}", file=sys.stderr)
    return True


def delete_subnets(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    code, out, _ = _run_aws(["ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        subnets = data.get("Subnets", [])
    except json.JSONDecodeError:
        return []
    deleted = []
    for sub in subnets:
        sub_id = sub.get("SubnetId")
        if not sub_id:
            continue
        if dry_run:
            print(f"  [dry-run] would delete subnet: {sub_id}")
            deleted.append(sub_id)
            continue
        code2, _, err = _run_aws(["ec2", "delete-subnet", "--subnet-id", sub_id], region)
        if code2 == 0:
            print(f"  deleted subnet: {sub_id}")
            deleted.append(sub_id)
        else:
            print(f"  failed subnet {sub_id}: {err.strip()[:120]}", file=sys.stderr)
    return deleted


def delete_custom_route_tables(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    code, out, _ = _run_aws(["ec2", "describe-route-tables", "--filters", f"Name=vpc-id,Values={vpc_id}"], region)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        rts = data.get("RouteTables", [])
    except json.JSONDecodeError:
        return []
    # Main route table has associations with Main=True; skip it (deleted with VPC)
    custom = [rt for rt in rts if not any(a.get("Main") for a in rt.get("Associations", []))]
    deleted = []
    for rt in custom:
        rt_id = rt.get("RouteTableId")
        if not rt_id:
            continue
        # Disassociate all non-main associations first
        for assoc in rt.get("Associations", []):
            if assoc.get("Main"):
                continue
            aid = assoc.get("RouteTableAssociationId")
            if not aid:
                continue
            if not dry_run:
                _run_aws(["ec2", "disassociate-route-table", "--association-id", aid], region)
        if dry_run:
            print(f"  [dry-run] would delete route table: {rt_id}")
            deleted.append(rt_id)
            continue
        code2, _, err = _run_aws(["ec2", "delete-route-table", "--route-table-id", rt_id], region)
        if code2 == 0:
            print(f"  deleted route table: {rt_id}")
            deleted.append(rt_id)
        else:
            print(f"  failed route table {rt_id}: {err.strip()[:120]}", file=sys.stderr)
    return deleted


def delete_vpc_endpoints(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    code, out, _ = _run_aws(
        ["ec2", "describe-vpc-endpoints", "--filters", f"Name=vpc-id,Values={vpc_id}"],
        region,
    )
    if code != 0:
        return []
    try:
        data = json.loads(out)
        endpoints = data.get("VpcEndpoints", [])
    except json.JSONDecodeError:
        return []
    deleted = []
    for ep in endpoints:
        ep_id = ep.get("VpcEndpointId")
        if not ep_id:
            continue
        if dry_run:
            print(f"  [dry-run] would delete VPC endpoint: {ep_id}")
            deleted.append(ep_id)
            continue
        code2, _, err = _run_aws(["ec2", "delete-vpc-endpoints", "--vpc-endpoint-ids", ep_id], region)
        if code2 == 0:
            print(f"  deleted VPC endpoint: {ep_id}")
            deleted.append(ep_id)
        else:
            print(f"  failed VPC endpoint {ep_id}: {err.strip()[:120]}", file=sys.stderr)
    return deleted


def delete_security_groups(vpc_id: str, region: str, dry_run: bool) -> list[str]:
    code, out, _ = _run_aws(
        ["ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={vpc_id}"],
        region,
    )
    if code != 0:
        return []
    try:
        data = json.loads(out)
        sgs = data.get("SecurityGroups", [])
    except json.JSONDecodeError:
        return []
    # Skip default SG (GroupName=default); it is deleted with the VPC
    custom = [sg for sg in sgs if sg.get("GroupName") != "default"]
    deleted = []
    deleted_ids = set()
    for sg in custom:
        sg_id = sg.get("GroupId")
        if not sg_id or sg_id in deleted_ids:
            continue
        if dry_run:
            print(f"  [dry-run] would delete security group: {sg_id} ({sg.get('GroupName', '')})")
            deleted.append(sg_id)
            continue
        code2, _, err = _run_aws(["ec2", "delete-security-group", "--group-id", sg_id], region)
        if code2 == 0:
            print(f"  deleted security group: {sg_id}")
            deleted.append(sg_id)
            deleted_ids.add(sg_id)
        elif "DependencyViolation" in err or "in use" in err.lower():
            # SG in use (ENI) - may need instances/LB terminated first; retry after a pass
            pass
        else:
            print(f"  failed security group {sg_id}: {err.strip()[:120]}", file=sys.stderr)
    # Retry up to 3 passes for SGs that had DependencyViolation (e.g. mutual refs)
    for _ in range(2):
        remaining = [sg for sg in custom if sg.get("GroupId") not in deleted_ids]
        if not remaining:
            break
        time.sleep(3)
        for sg in remaining:
            sg_id = sg.get("GroupId")
            if not sg_id:
                continue
            code2, _, err = _run_aws(["ec2", "delete-security-group", "--group-id", sg_id], region)
            if code2 == 0:
                print(f"  deleted security group: {sg_id}")
                deleted.append(sg_id)
                deleted_ids.add(sg_id)
    return deleted


def delete_vpc(vpc_id: str, region: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would delete VPC: {vpc_id}")
        return True
    code, _, err = _run_aws(["ec2", "delete-vpc", "--vpc-id", vpc_id], region)
    if code == 0:
        print(f"  deleted VPC: {vpc_id}")
        return True
    print(f"  failed VPC {vpc_id}: {err.strip()[:120]}", file=sys.stderr)
    return False


def delete_vpc_cascade(vpc: dict, region: str, dry_run: bool, terminate_instances: bool = False) -> bool:
    vpc_id = vpc.get("VpcId")
    name = _get_tag(vpc, "Name") or "-"
    print(f"\n--- VPC {vpc_id} (Name={name}) ---")
    # 1. NAT Gateways
    deleted_nats = delete_nat_gateways(vpc_id, region, dry_run)
    if deleted_nats and not dry_run:
        for nat_id in deleted_nats:
            wait_nat_deleted(nat_id, region)
    # 2. Load balancers
    deleted_lbs = delete_load_balancers(vpc_id, region, dry_run)
    if deleted_lbs and not dry_run:
        print("  waiting for load balancers to drain (15s)...")
        time.sleep(15)
    # 3. EC2 instances (if requested)
    if terminate_instances:
        terminated = _terminate_instances_in_vpc(vpc_id, region, dry_run)
        if terminated and not dry_run:
            print("  waiting for instances to terminate (30s)...")
            time.sleep(30)
    # 4. IGW
    detach_and_delete_igw(vpc_id, region, dry_run)
    # 5. Subnets
    delete_subnets(vpc_id, region, dry_run)
    # 6. Custom route tables
    delete_custom_route_tables(vpc_id, region, dry_run)
    # 7. VPC endpoints
    delete_vpc_endpoints(vpc_id, region, dry_run)
    # 8. Security groups (non-default)
    delete_security_groups(vpc_id, region, dry_run)
    # 9. VPC
    return delete_vpc(vpc_id, region, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete non-default VPCs and their resources (NAT, IGW, subnets, route tables)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    parser.add_argument("-r", "--region", default=_DEFAULT_REGION, help="AWS region")
    parser.add_argument("--vpc-id", metavar="ID", help="Delete only this VPC")
    parser.add_argument("--prefix", metavar="PREFIX", help="Only VPCs whose Name tag starts with PREFIX")
    parser.add_argument("--terminate-instances", action="store_true", help="Terminate EC2 instances in the VPC")
    parser.add_argument("--dry-run", action="store_true", help="Show actions, no changes")
    args = parser.parse_args()

    region = args.region

    if args.vpc_id:
        code, out, err = _run_aws(["ec2", "describe-vpcs", "--vpc-ids", args.vpc_id], region)
        if code != 0:
            print(f"Error: could not find VPC {args.vpc_id}: {err.strip()}", file=sys.stderr)
            return 1
        try:
            data = json.loads(out)
            vpcs = data.get("Vpcs", [])
        except json.JSONDecodeError:
            vpcs = []
        if not vpcs:
            print(f"VPC {args.vpc_id} not found.")
            return 1
        v = vpcs[0]
        if v.get("IsDefault"):
            print("Error: cannot delete the default VPC.")
            return 1
        vpcs = [v]
    else:
        vpcs = list_non_default_vpcs(region, args.prefix)
        if not vpcs:
            print("No non-default VPCs found" + (f" with Name prefix '{args.prefix}'" if args.prefix else "") + ".")
            return 0

    print(f"VPCs to delete ({region}):")
    for v in vpcs:
        name = _get_tag(v, "Name") or "-"
        print(f"  - {v['VpcId']}  Name={name}")
    if not args.yes and not args.dry_run:
        try:
            answer = input("\nProceed? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input).")
            return 0

    ok = True
    for v in vpcs:
        if not delete_vpc_cascade(v, region, args.dry_run, args.terminate_instances):
            ok = False

    if args.dry_run:
        print("\n[dry-run] No changes made.")
    elif ok:
        print("\nDone.")
    else:
        print("\nSome deletions failed. Check errors above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
