# Scripts

| Script | Purpose | Doc |
|--------|---------|-----|
| `upload-for-hf.py` | Upload project to Hugging Face model repo | [DEPLOY.md](../DEPLOY.md#hugging-face) |
| `upload-space-app.py` | Upload Space app (app.py, Dockerfile) to HF Space | [DEPLOY.md](../DEPLOY.md#hugging-face) |
| `delete-s3-buckets.py` | Empty and delete S3 buckets | [DELETE_S3_BUCKETS.md](DELETE_S3_BUCKETS.md) |
| `delete-platform-iam.py` | Delete orphaned IAM roles / instance profiles | [DELETE-PLATFORM-IAM.md](DELETE-PLATFORM-IAM.md) |
| `resolve-aws-limits.py` | Release unassociated EIPs, list VPCs (VpcLimitExceeded) | — |
| `remove-terraform-blockers.py` | Delete CloudTrail trails, release EIPs blocking Terraform | — |
| `remove-cloudwatch-logs.py` | Delete CloudWatch log groups blocking Terraform | — |
