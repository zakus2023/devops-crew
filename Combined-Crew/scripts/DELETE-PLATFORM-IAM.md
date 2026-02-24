# Delete Platform IAM Roles and Instance Profiles

This script deletes the IAM roles and instance profiles created by the platform Terraform module so Terraform can recreate them cleanly. Use it when:

- Terraform destroy left orphaned IAM roles
- You get **"Cannot delete entity, must remove roles from instance profile first"** when deleting roles
- You want a clean slate before re-running `terraform apply`

---

## What It Deletes

For each environment (dev, prod), the script removes:

| Resource              | Name pattern                          |
|-----------------------|---------------------------------------|
| EC2 instance profile  | `{project}-{env}-ec2-profile`         |
| EC2 role              | `{project}-{env}-ec2-role`            |
| CodeDeploy role       | `{project}-{env}-codedeploy-role`     |

Example (project=bluegreen): `bluegreen-dev-ec2-profile`, `bluegreen-dev-ec2-role`, `bluegreen-dev-codedeploy-role`, and the same for prod.

---

## AWS Deletion Order

IAM roles tied to instance profiles cannot be deleted directly. The script follows this order:

1. **Disassociate** the instance profile from any EC2 instances
2. **Remove** the role from the instance profile
3. **Delete** the instance profile
4. **Detach** all managed and inline policies from the role
5. **Delete** the role

---

## Usage

From the project root:

```bash
# Delete dev and prod (default)
python Combined-Crew/scripts/delete-platform-iam.py

# Delete dev only
python Combined-Crew/scripts/delete-platform-iam.py --env dev

# Delete prod only
python Combined-Crew/scripts/delete-platform-iam.py --env prod

# Delete both explicitly
python Combined-Crew/scripts/delete-platform-iam.py --env dev --env prod

# Preview without changes
python Combined-Crew/scripts/delete-platform-iam.py --dry-run
```

### Options

| Option        | Short | Default   | Description                         |
|---------------|-------|-----------|-------------------------------------|
| `--region`    | `-r`  | us-east-1 | AWS region                          |
| `--project`   | `-p`  | bluegreen | Project name (for resource names)   |
| `--env`       | `-e`  | dev, prod | Environment(s) to delete. Repeat for multiple. |
| `--dry-run`   |       |           | Show what would be done, no changes |

---

## Prerequisites

- **AWS CLI** installed and configured (`aws configure` or env vars)
- Sufficient IAM permissions to delete IAM roles, instance profiles, and disassociate from EC2

---

## After Running

You can then:

1. Run `terraform apply` again — Terraform will create the roles and instance profiles fresh
2. Or use `run_import_platform_iam_on_conflict` — if the roles still exist in AWS, the pipeline can import them into state instead of deleting (see [IMPLEMENTATION.md](../IMPLEMENTATION.md))

---

## Related Scripts

- **resolve-aws-limits.py** — Release unassociated EIPs when hitting VPC/EIP limits
- **remove-terraform-blockers.py** — Delete CloudTrail trails that block Terraform apply
