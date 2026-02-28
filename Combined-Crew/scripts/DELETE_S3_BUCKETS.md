# Delete S3 Buckets

Script to delete S3 buckets from the CLI. Empties each bucket first (required before delete). Handles versioned buckets (e.g. Terraform tfstate) by deleting all object versions and delete markers before bucket deletion.

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured
- Credentials set via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or `aws configure`

## Usage

```bash
# From project root
python Combined-Crew/scripts/delete-s3-buckets.py [OPTIONS] [BUCKET1 BUCKET2 ...]
```

## Options

| Option | Description |
|--------|-------------|
| `-y`, `--yes` | Skip confirmation prompt |
| `-r`, `--region` | AWS region (default: `us-east-1`) |
| `--from-output DIR` | Read bucket names from Terraform output in given directory |
| `--prefix PREFIX` | List and delete buckets whose names start with PREFIX |
| `--list-only` | With `--prefix`: only list buckets, do not delete |

## Examples

### Delete specific buckets

```bash
python Combined-Crew/scripts/delete-s3-buckets.py my-bucket-1 my-bucket-2
```

### Skip confirmation

```bash
python Combined-Crew/scripts/delete-s3-buckets.py my-bucket -y
```

### Specify region

```bash
python Combined-Crew/scripts/delete-s3-buckets.py my-bucket -r us-west-2 -y
```

### Read from Terraform output

Use when you have the pipeline output directory (e.g. from Download output):

```bash
python Combined-Crew/scripts/delete-s3-buckets.py --from-output ./output -y
```

Reads `tfstate_bucket`, `cloudtrail_bucket`, and `artifacts_bucket` from Terraform outputs.

### Delete by prefix

Delete all buckets whose names start with a prefix (e.g. `bluegreen-`):

```bash
# List first
python Combined-Crew/scripts/delete-s3-buckets.py --prefix bluegreen- --list-only

# Delete
python Combined-Crew/scripts/delete-s3-buckets.py --prefix bluegreen- -r us-east-1 -y
```

### Example: bluegreen project buckets

```bash
python Combined-Crew/scripts/delete-s3-buckets.py \
  bluegreen-cloudtrail-20260227044358368300000002 \
  bluegreen-dev-codedeploy-20260227044443556800000002 \
  bluegreen-prod-codedeploy-20260227044826643000000001 \
  bluegreen-tfstate-20260227044358366800000001 \
  -r us-east-1 -y
```

Or by prefix:

```bash
python Combined-Crew/scripts/delete-s3-buckets.py --prefix bluegreen- -r us-east-1 -y
```

## Notes

- Buckets are emptied before deletion
- **Versioned buckets** (e.g. Terraform tfstate): if `s3 rb --force` fails with `BucketNotEmpty`, the script automatically deletes all object versions and delete markers, then removes the bucket
- `--from-output` requires Terraform to be installed and the output directory to exist with applied infra
- `list-buckets` is global; `--prefix` lists from all regions
- Deletion uses the region for the `s3 rb` operation
