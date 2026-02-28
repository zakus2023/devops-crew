#!/usr/bin/env python3
"""
Delete S3 buckets from the CLI. Empties each bucket first (required before delete).

Usage:
  python Combined-Crew/scripts/delete-s3-buckets.py BUCKET1 BUCKET2 ...
  python Combined-Crew/scripts/delete-s3-buckets.py --from-output ./output
  python Combined-Crew/scripts/delete-s3-buckets.py --prefix myapp-tfstate --region us-east-1
  python Combined-Crew/scripts/delete-s3-buckets.py BUCKET1 -y

Options:
  -y, --yes       Skip confirmation prompt
  -r, --region    AWS region (default: us-east-1)
  --from-output   Read bucket names from Terraform output in given directory
  --prefix        List and delete buckets whose names start with this prefix
  --list-only     With --prefix: only list buckets, do not delete
"""
import argparse
import json
import os
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COMBINED_CREW = os.path.dirname(_SCRIPT_DIR)


def _run(cmd: list, timeout: int = 300) -> tuple[bool, str]:
    """Run command, return (success, stderr_or_stdout on failure)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if r.returncode == 0:
            return True, r.stdout or ""
        return False, r.stderr or r.stdout or f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "aws CLI not found in PATH"
    except Exception as e:
        return False, str(e)


def list_buckets_with_prefix(prefix: str) -> list[str]:
    """List S3 bucket names that start with the given prefix. list-buckets is global (no region)."""
    ok, out = _run(
        ["aws", "s3api", "list-buckets", "--query", "Buckets[].Name", "--output", "text"],
        timeout=30,
    )
    if not ok:
        return []
    names = [n.strip() for n in (out or "").split() if n.strip() and n.strip().startswith(prefix)]
    return names


def _empty_versioned_bucket(bucket: str, region: str) -> bool:
    """Empty a versioned bucket by deleting all object versions and delete markers."""
    env = os.environ.copy()
    env["AWS_DEFAULT_REGION"] = region
    key_version_id_pairs = []
    next_key_marker = None
    next_version_id_marker = None

    while True:
        cmd = ["aws", "s3api", "list-object-versions", "--bucket", bucket, "--output", "json"]
        if next_key_marker:
            cmd.extend(["--key-marker", next_key_marker])
        if next_version_id_marker:
            cmd.extend(["--version-id-marker", next_version_id_marker])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=env)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        if r.returncode != 0:
            return False

        data = json.loads(r.stdout or "{}")
        for obj in data.get("Versions", []) + data.get("DeleteMarkers", []):
            key = obj.get("Key")
            vid = obj.get("VersionId")
            if key is not None:
                key_version_id_pairs.append((key, vid))

        is_truncated = data.get("IsTruncated", False)
        if not is_truncated:
            break
        next_key_marker = data.get("NextKeyMarker")
        next_version_id_marker = data.get("NextVersionIdMarker")

    for key, version_id in key_version_id_pairs:
        cmd = ["aws", "s3api", "delete-object", "--bucket", bucket, "--key", key]
        if version_id:
            cmd.extend(["--version-id", version_id])
        subprocess.run(cmd, capture_output=True, timeout=30, env=env)

    return True


def delete_bucket_force(bucket: str, region: str) -> bool:
    """Empty and delete an S3 bucket. Handles versioned buckets (tfstate, etc.)."""
    env = os.environ.copy()
    env["AWS_DEFAULT_REGION"] = region
    try:
        r = subprocess.run(
            ["aws", "s3", "rb", f"s3://{bucket}", "--force"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            env=env,
        )
        if r.returncode == 0:
            return True
        err = (r.stderr or r.stdout or "").strip()
        if "BucketNotEmpty" in err or "delete all versions" in err.lower():
            print(f"  Bucket is versioned, deleting all versions...")
            if not _empty_versioned_bucket(bucket, region):
                print(f"  Error: could not empty versioned bucket")
                return False
            r2 = subprocess.run(
                ["aws", "s3api", "delete-bucket", "--bucket", bucket],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env=env,
            )
            if r2.returncode == 0:
                return True
            print(f"  Error: {(r2.stderr or r2.stdout or '')[:300]}")
            return False
        print(f"  Error: {err[:300]}")
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Error: {e}")
        return False


def get_buckets_from_output(output_dir: str) -> list[str]:
    """Get S3 bucket names from Terraform outputs in the output directory."""
    buckets = []
    bootstrap_dir = os.path.join(output_dir, "infra", "bootstrap")
    if not os.path.isdir(bootstrap_dir):
        return buckets

    for name in ["tfstate_bucket", "cloudtrail_bucket", "tflock_table"]:
        if name == "tflock_table":
            continue  # DynamoDB table, not S3
        ok, out = _run(
            ["terraform", "output", "-raw", name],
            cwd=bootstrap_dir,
            timeout=30,
        )
        if ok and out:
            val = out.strip()
            if val and not any(c in val for c in ("╷", "╵", "│", "\x1b", "\n")):
                buckets.append(val)

    # Also check dev/prod for artifacts_bucket if present
    for env in ("dev", "prod"):
        env_dir = os.path.join(output_dir, "infra", "envs", env)
        if not os.path.isdir(env_dir):
            continue
        ok, out = _run(
            ["terraform", "output", "-raw", "artifacts_bucket"],
            cwd=env_dir,
            timeout=30,
        )
        if ok and out:
            val = out.strip()
            if val and val not in buckets:
                buckets.append(val)

    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete S3 buckets. Empties each bucket first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("buckets", nargs="*", help="Bucket names to delete")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    parser.add_argument("-r", "--region", default="us-east-1", help="AWS region")
    parser.add_argument("--from-output", metavar="DIR", help="Read bucket names from Terraform output in DIR")
    parser.add_argument("--prefix", metavar="PREFIX", help="Delete buckets whose names start with PREFIX")
    parser.add_argument("--list-only", action="store_true", help="With --prefix: only list, do not delete")
    args = parser.parse_args()

    buckets = list(args.buckets)

    if args.from_output:
        out_dir = os.path.abspath(args.from_output)
        if not os.path.isdir(out_dir):
            print(f"Error: output directory not found: {out_dir}")
            return 1
        found = get_buckets_from_output(out_dir)
        buckets.extend(found)
        if found:
            print(f"From Terraform output in {out_dir}: {found}")

    if args.prefix:
        found = list_buckets_with_prefix(args.prefix)
        if not found:
            print(f"No buckets found with prefix: {args.prefix}")
            return 0
        buckets.extend(found)
        if args.list_only:
            print("Buckets matching prefix:")
            for b in found:
                print(f"  {b}")
            return 0

    buckets = list(dict.fromkeys(buckets))  # dedupe preserving order
    if not buckets:
        print("No buckets specified. Use --help for usage.")
        return 1

    print(f"Bucket(s) to delete: {buckets}")
    if not args.yes:
        try:
            answer = input("Proceed? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input).")
            return 0

    region = args.region
    failed = []
    for bucket in buckets:
        print(f"Deleting {bucket} (emptying first)...")
        if not delete_bucket_force(bucket, region):
            failed.append(bucket)
        else:
            print(f"  Deleted {bucket}")

    if failed:
        print(f"\nFailed: {failed}")
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
