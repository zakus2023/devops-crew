"""
Tools for the Multi-Agent Deploy Pipeline: Terraform, Build, Deploy, Verify.
All paths are relative to repo_root (the CICD-With-AI repo root).
"""
import os
import subprocess
from typing import Optional

import requests

try:
    from crewai.tools import tool
except ImportError:
    def tool(desc):
        def deco(fn):
            fn.description = desc
            return fn
        return deco

# Repo root is set when creating the crew (path to CICD-With-AI for Terraform/infra)
_REPO_ROOT: Optional[str] = None
# Optional app root: when set (e.g. crew-DevOps/app), docker_build uses this instead of repo_root/app
_APP_ROOT: Optional[str] = None


def set_repo_root(path: str) -> None:
    global _REPO_ROOT
    _REPO_ROOT = path


def set_app_root(path: Optional[str]) -> None:
    global _APP_ROOT
    _APP_ROOT = path


def get_repo_root() -> str:
    if _REPO_ROOT is None:
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cicd = os.path.join(parent, "CICD-With-AI")
        return cicd if os.path.isdir(cicd) else parent
    return _REPO_ROOT


def get_app_root() -> Optional[str]:
    """If set, use this path for docker build; else build from repo_root/app."""
    return _APP_ROOT


@tool("Run 'terraform init' in a Terraform directory. Input: relative_path from repo root, e.g. 'infra/bootstrap' or 'infra/envs/dev'. Optional backend_config, e.g. 'backend.hcl' for envs.")
def terraform_init(relative_path: str, backend_config: Optional[str] = None) -> str:
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    cmd = ["terraform", "init"]
    if backend_config:
        cmd.extend(["-backend-config", backend_config, "-reconfigure"])
    try:
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return f"terraform init in {relative_path}: OK"
        return f"terraform init in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Run 'terraform plan' in a Terraform directory. Input: relative_path (e.g. infra/envs/prod), var_file (e.g. prod.tfvars) optional.")
def terraform_plan(relative_path: str, var_file: Optional[str] = None) -> str:
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    cmd = ["terraform", "plan"]
    if var_file:
        cmd.extend(["-var-file", var_file])
    try:
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return f"terraform plan in {relative_path}: OK\n{result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout}"
        return f"terraform plan in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Run 'terraform apply -auto-approve' in a Terraform directory. Only runs if ALLOW_TERRAFORM_APPLY=1. Input: relative_path, var_file optional.")
def terraform_apply(relative_path: str, var_file: Optional[str] = None) -> str:
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        return "terraform apply skipped: set ALLOW_TERRAFORM_APPLY=1 to allow apply. Run terraform plan first to review changes."
    root = get_repo_root()
    work_dir = os.path.join(root, relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    cmd = ["terraform", "apply", "-auto-approve"]
    if var_file:
        cmd.extend(["-var-file", var_file])
    try:
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            return f"terraform apply in {relative_path}: OK"
        return f"terraform apply in {relative_path}: FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: terraform not found in PATH."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Run 'docker build' for the app. Input: app_relative_path (default 'app'), tag (e.g. latest or a version). Uses APP_ROOT when set (e.g. crew-DevOps/app), else repo_root/app.")
def docker_build(app_relative_path: str = "app", tag: str = "latest") -> str:
    app_root = get_app_root()
    root = get_repo_root()
    work_dir = app_root if app_root else os.path.join(root, app_relative_path)
    if not os.path.isdir(work_dir):
        return f"Error: directory not found: {work_dir}"
    try:
        result = subprocess.run(
            ["docker", "build", "-t", f"app:{tag}", "."],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return f"docker build in {work_dir}: OK (tag app:{tag})"
        return f"docker build FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: docker not found in PATH."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Push Docker image to ECR and update SSM image_tag. Input: ecr_repo_name (e.g. bluegreen-prod-app), image_tag (e.g. 202602081200), aws_region optional (default from env). Uses app:image_tag as local image; tags and pushes to ECR then puts SSM /bluegreen/prod/image_tag.")
def ecr_push_and_ssm(ecr_repo_name: str, image_tag: str, aws_region: Optional[str] = None) -> str:
    region = aws_region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        sts = boto3.client("sts", region_name=region)
        account = sts.get_caller_identity()["Account"]
        ecr_uri = f"{account}.dkr.ecr.{region}.amazonaws.com/{ecr_repo_name}:{image_tag}"
        # Tag local image
        result = subprocess.run(
            ["docker", "tag", f"app:{image_tag}", ecr_uri],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"docker tag failed: {result.stderr}"
        # ECR login
        login = subprocess.run(
            ["aws", "ecr", "get-login-password", "--region", region],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if login.returncode != 0:
            return f"ECR login failed: {login.stderr}"
        login_cmd = subprocess.Popen(
            ["docker", "login", "--username", "AWS", "--password-stdin",
             f"{account}.dkr.ecr.{region}.amazonaws.com"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out, err = login_cmd.communicate(input=login.stdout, timeout=15)
        if login_cmd.returncode != 0:
            return f"docker login failed: {err}"
        # Push
        push = subprocess.run(
            ["docker", "push", ecr_uri],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if push.returncode != 0:
            return f"docker push failed: {push.stderr}"
        # SSM put
        ssm = boto3.client("ssm", region_name=region)
        ssm.put_parameter(
            Name="/bluegreen/prod/image_tag",
            Value=image_tag,
            Type="String",
            Overwrite=True,
        )
        return f"ECR push and SSM update OK: {ecr_uri}, /bluegreen/prod/image_tag = {image_tag}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@tool("Read an AWS SSM Parameter Store value. Input: parameter name (e.g. /bluegreen/prod/image_tag), region optional.")
def read_ssm_parameter(name: str, region: Optional[str] = None) -> str:
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=region)
        resp = ssm.get_parameter(Name=name, WithDecryption=True)
        value = resp["Parameter"]["Value"]
        return f"SSM {name} = {value}"
    except Exception as e:
        return f"SSM {name} error: {type(e).__name__}: {str(e)[:200]}"


@tool("Run Ansible deploy playbook over SSM. Input: env (prod or dev), ssm_bucket (S3 bucket for SSM transfer, e.g. from terraform output artifacts_bucket), ansible_dir relative to repo (default ansible). Runs: ansible-playbook -i inventory/ec2_{env}.aws_ec2.yml playbooks/deploy.yml -e ssm_bucket=... -e env=...")
def run_ansible_deploy(env: str = "prod", ssm_bucket: str = "", ansible_dir: str = "ansible", region: Optional[str] = None) -> str:
    if not ssm_bucket:
        return "Error: ssm_bucket is required. Get it from terraform output -raw artifacts_bucket in infra/envs/prod (or dev)."
    root = get_repo_root()
    work_dir = os.path.join(root, ansible_dir)
    if not os.path.isdir(work_dir):
        return f"Error: ansible directory not found: {work_dir}"
    inv = f"inventory/ec2_{env}.aws_ec2.yml"
    inv_path = os.path.join(work_dir, inv)
    if not os.path.isfile(inv_path):
        return f"Error: inventory not found: {inv_path}"
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    cmd = [
        "ansible-playbook",
        "-i", inv,
        "playbooks/deploy.yml",
        "-e", f"ssm_bucket={ssm_bucket}",
        "-e", f"env={env}",
        "-e", f"ssm_region={region}",
    ]
    try:
        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            return f"Ansible deploy ({env}): OK\n{result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout}"
        return f"Ansible deploy ({env}): FAIL\nstderr: {result.stderr}\nstdout: {result.stdout}"
    except FileNotFoundError:
        return "Error: ansible-playbook not found in PATH. Install Ansible and community.aws collection (ansible-galaxy collection install community.aws)."
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:200]}"


@tool("Trigger CodeDeploy deployment. Input: application_name (e.g. bluegreen-prod), deployment_group_name (e.g. bluegreen-prod-dg), region optional. Requires s3_bucket and s3_key for revision (e.g. from build output). For simple case, pass bucket and key if you have a deploy bundle.")
def trigger_codedeploy(application_name: str, deployment_group_name: str, s3_bucket: Optional[str] = None, s3_key: Optional[str] = None, region: Optional[str] = None) -> str:
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3
        client = boto3.client("codedeploy", region_name=region)
        if s3_bucket and s3_key:
            revision = {"revisionType": "S3", "s3Location": {"bucket": s3_bucket, "key": s3_key, "bundleType": "zip"}}
        else:
            return "Error: s3_bucket and s3_key required for CodeDeploy revision. Build the deploy bundle first and upload to S3."
        resp = client.create_deployment(
            applicationName=application_name,
            deploymentGroupName=deployment_group_name,
            revision=revision,
        )
        return f"CodeDeploy deployment started: {resp.get('deploymentId')}"
    except Exception as e:
        return f"CodeDeploy error: {type(e).__name__}: {str(e)[:200]}"


@tool("Check HTTP/HTTPS health of a URL. Input: full URL (e.g. https://app.example.com/health). Returns status code and OK or NOT OK.")
def http_health_check(url: str, timeout_seconds: int = 10) -> str:
    if not url:
        return "Error: URL is empty."
    try:
        r = requests.get(url, verify=True, timeout=timeout_seconds)
        ok = 200 <= r.status_code < 300
        return f"URL: {url} | Status: {r.status_code} | {'OK' if ok else 'NOT OK'}"
    except Exception as e:
        return f"URL: {url} | Error: {type(e).__name__}: {str(e)[:200]}"
