# Delete VPC Resources (Non-Default)

Script to delete non-default VPCs and their dependent resources from the CLI. Safely skips the default VPC.

## What It Deletes

For each non-default VPC, in order:

| Order | Resource        | Notes                                                |
|-------|-----------------|------------------------------------------------------|
| 1     | NAT Gateways    | Waits for deletion (releases Elastic IPs)            |
| 2     | Load Balancers  | ALB/NLB in the VPC (automatically deleted)           |
| 3     | EC2 Instances   | Only with `--terminate-instances`                     |
| 4     | Internet Gateways | Detaches from VPC, then deletes                     |
| 5     | Subnets         | Must be empty after LB/instance removal              |
| 6     | Route Tables    | Non-main only; main is deleted with VPC               |
| 7     | VPC Endpoints   | Gateway and interface endpoints                      |
| 8     | Security Groups | Non-default SGs (default deleted with VPC)            |
| 9     | VPC             | Cleans up remaining resources                         |

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured
- Use `--terminate-instances` if EC2 instances exist in the VPC.

## Usage

```bash
# From project root
python Combined-Crew/scripts/delete-vpc-resources.py [OPTIONS]
```

## Options

| Option        | Description                                      |
|---------------|--------------------------------------------------|
| `-y`, `--yes` | Skip confirmation prompt                         |
| `-r`, `--region` | AWS region (default: `us-east-1`)               |
| `--vpc-id ID` | Delete only this VPC (must be non-default)       |
| `--prefix PREFIX` | Only delete VPCs whose Name tag starts with PREFIX |
| `--terminate-instances` | Terminate EC2 instances in the VPC (required if instances exist) |
| `--dry-run`   | Show what would be deleted, make no changes      |

## Examples

### Delete all non-default VPCs

```bash
python Combined-Crew/scripts/delete-vpc-resources.py -y
```

### Delete a specific VPC

```bash
python Combined-Crew/scripts/delete-vpc-resources.py --vpc-id vpc-036396a4477a50970 -y
```

### Delete VPCs by Name prefix

```bash
# Preview first
python Combined-Crew/scripts/delete-vpc-resources.py --prefix bluegreen --dry-run

# Then delete
python Combined-Crew/scripts/delete-vpc-resources.py --prefix bluegreen -r us-east-1 -y

# If EC2 instances or load balancers block deletion, add --terminate-instances
python Combined-Crew/scripts/delete-vpc-resources.py --prefix bluegreen -r us-east-1 -y --terminate-instances
```

### Specify region

```bash
python Combined-Crew/scripts/delete-vpc-resources.py -r us-west-2 -y
```

## Notes

- **Default VPC**: Never deleted. Use `--vpc-id` with a non-default VPC.
- **Load balancers**: Deleted automatically before subnets.
- **EC2 instances**: Use `--terminate-instances` if instances block deletion. This terminates all instances in the VPC.
- **Security groups / VPC endpoints**: Deleted automatically before VPC.
- **NAT Gateway**: Takes 1–2 minutes to delete; the script waits before continuing.
- **Elastic IPs**: Released automatically when NAT gateways are deleted.

## Related Scripts

- **resolve-aws-limits.py** — Release unassociated EIPs, list VPCs
- **delete-s3-buckets.py** — Delete S3 buckets
- **delete-platform-iam.py** — Delete platform IAM roles
