# Multi-Agent Deploy Pipeline

Run a **four-step deployment flow** on your **deployment project**: **Terraform → Build → Deploy → Verify**, using four specialist CrewAI agents.

This folder lives in **crew-DevOps** (next to Full-Orchestrator). You point it at a **deployment project** via **REPO_ROOT** (e.g. **Full-Orchestrator/output**). When **crew-DevOps/app** exists, the Build step uses that app for Docker build (set **APP_ROOT** to override).

- **EXPLANATION.md** — Beginner-level: what it is, why use it, how it works.
- **IMPLEMENTATION.md** — Step-by-step: setup, commands, deploy options (including ssh_script).

## Quick start

```bash
cd Multi-Agent-Pipeline
python -m venv .venv
source .venv/Scripts/activate   # Bash (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
copy .env.example .env   # Windows; use cp on Linux/macOS
# Edit .env: PROD_URL, OPENAI_API_KEY, and optionally DEPLOY_METHOD, SSH_KEY_PATH
python run.py
```

Pipeline order: **Infra (Terraform)** → **Build (Docker + ECR + SSM)** → **Deploy** → **Verify (health + SSM)**.

Set `ALLOW_TERRAFORM_APPLY=1` to allow Terraform apply. Set **DEPLOY_METHOD** to choose how Deploy runs: **codedeploy**, **ansible**, **ssh_script**, or **ecs**.

---

## Quick path: ssh_script deploy (step-by-step)

If you want to deploy via **SSH** (no Ansible, no CodeDeploy), follow these steps. The pipeline will SSH into each EC2 instance tagged `Env=prod`, pull the new image from ECR, and run the app container.

| Step | Action |
|------|--------|
| 1 | In `.env` set `DEPLOY_METHOD=ssh_script`. |
| 2 | Set `SSH_KEY_PATH` to the **full path** of your `.pem` file (e.g. `C:/My-Projects/crew-DevOps/my-key.pem`). This key must match the AWS key pair used by your EC2 instances (and bastion, if used). |
| 3 | Ensure your app EC2 instances have the tag **Env=prod** (or **Env=dev**). The pipeline discovers instances by this tag. |
| 4 | **If instances are in private subnets:** In Terraform (e.g. `infra/envs/prod/prod.tfvars`) set `enable_bastion = true` and `key_name = "YOUR_KEY_PAIR_NAME"`, then apply. In `.env` leave **BASTION_HOST** unset so the pipeline auto-reads the bastion IP from Terraform. |
| 5 | Run `python run.py`. The Deploy step will connect (via bastion if configured), run ECR login and `sudo docker pull`, then start the new container on each instance. |

**Troubleshooting:** Permission denied on the bastion → ensure your `.pem` matches the bastion’s key pair; test with `ssh -i /path/to/key.pem ec2-user@BASTION_IP "echo OK"`. Permission denied on Docker → the script uses `sudo docker`; ensure Docker is installed and `ec2-user` has sudo. See **IMPLEMENTATION.md** (§6.3, ssh_script step-by-step) for more.

---

## Step-by-step: How Multi-Agent-Pipeline was implemented (beginner level)

This section walks through building the Multi-Agent-Pipeline **in order**, with **full file contents** so you can recreate or compare.

**Prerequisites:** Python 3.10+; CICD-With-AI repo (or set REPO_ROOT). Optional: Terraform, Docker, Ansible for the tools to run.

**Folder layout when done:**

```
Multi-Agent-Pipeline/
├── .env.example
├── .gitignore
├── agents.py
├── flow.py
├── requirements.txt
├── run.py
├── tools.py
├── README.md
├── EXPLANATION.md
└── IMPLEMENTATION.md
```

---

### Step 1 — Create the folder and `requirements.txt`

**File: `Multi-Agent-Pipeline/requirements.txt`**

```text
# Multi-Agent Deploy Pipeline: Terraform → Build → Deploy → Verify
crewai>=0.80.0
crewai-tools>=0.14.0
requests>=2.28.0
boto3>=1.26.0
python-dotenv>=1.0.0
```

---

### Step 2 — Create `.env.example`

**File: `Multi-Agent-Pipeline/.env.example`**

```text
# Copy to .env and fill in. Do not commit .env.

# Production base URL (no /health) - required
PROD_URL=https://app.example.com

# AWS region (optional; default us-east-1)
AWS_REGION=us-east-1

# Repo root = path to CICD-With-AI (optional; when in crew-DevOps, default is CICD-With-AI in this repo)
# REPO_ROOT=C:/My-Projects/crew-DevOps/CICD-With-AI

# Set to 1 to allow Terraform apply (default: plan only)
# ALLOW_TERRAFORM_APPLY=1

# Deploy method: codedeploy or ansible (deploy agent uses this to choose which tool to run)
# DEPLOY_METHOD=codedeploy
# DEPLOY_METHOD=ansible

# LLM for CrewAI (required)
OPENAI_API_KEY=sk-your-openai-key-here
```

---

### Step 3 — Create `.gitignore`

**File: `Multi-Agent-Pipeline/.gitignore`**

```text
.venv/
.env
__pycache__/
*.pyc
```

---

### Step 4 — Create `tools.py`

All tools run relative to `repo_root` (set by `set_repo_root` in flow). Tools: Terraform init/plan/apply, Docker build, ECR push + SSM, read SSM, Ansible deploy, CodeDeploy trigger, HTTP health check.

**File: `Multi-Agent-Pipeline/tools.py`**

```python
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

# Repo root is set when creating the crew (path to CICD-With-AI)
_REPO_ROOT: Optional[str] = None


def set_repo_root(path: str) -> None:
    global _REPO_ROOT
    _REPO_ROOT = path


def get_repo_root() -> str:
    if _REPO_ROOT is None:
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cicd = os.path.join(parent, "CICD-With-AI")
        return cicd if os.path.isdir(cicd) else parent
    return _REPO_ROOT


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


@tool("Run 'docker build' for the app. Input: app_relative_path (default 'app'), tag (e.g. latest or a version).")
def docker_build(app_relative_path: str = "app", tag: str = "latest") -> str:
    root = get_repo_root()
    work_dir = os.path.join(root, app_relative_path)
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
            return f"docker build in {app_relative_path}: OK (tag app:{tag})"
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
        result = subprocess.run(
            ["docker", "tag", f"app:{image_tag}", ecr_uri],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"docker tag failed: {result.stderr}"
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
        push = subprocess.run(
            ["docker", "push", ecr_uri],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if push.returncode != 0:
            return f"docker push failed: {push.stderr}"
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
```

---

### Step 5 — Create `agents.py`

Four agents, each with a subset of tools: Infra Engineer (Terraform), Build Engineer (Docker, ECR, SSM), Deploy Engineer (CodeDeploy, Ansible, SSM), Verifier (health, SSM).

**File: `Multi-Agent-Pipeline/agents.py`**

```python
"""
Multi-Agent Deploy Pipeline: four specialist agents.
- Infra Engineer: Terraform init, plan, apply (bootstrap, dev, prod).
- Build Engineer: Docker build, ECR push, SSM image_tag update.
- Deploy Engineer: Trigger CodeDeploy or Ansible (via DEPLOY_METHOD).
- Verifier: HTTP health check and SSM read to confirm deployment.
"""
from crewai import Agent

from tools import (
    terraform_init,
    terraform_plan,
    terraform_apply,
    docker_build,
    ecr_push_and_ssm,
    read_ssm_parameter,
    trigger_codedeploy,
    run_ansible_deploy,
    http_health_check,
)


infra_engineer = Agent(
    role="Infrastructure Engineer",
    goal="Run Terraform init, plan, and (if allowed) apply for bootstrap, dev, and prod so infrastructure is ready for the app.",
    backstory="You are a careful infrastructure engineer. You run terraform init with the correct backend config for each environment, then terraform plan to show changes, and terraform apply only when ALLOW_TERRAFORM_APPLY=1 is set. You work in the repo's infra/bootstrap, infra/envs/dev, infra/envs/prod.",
    tools=[terraform_init, terraform_plan, terraform_apply],
    verbose=True,
    allow_delegation=False,
)

build_engineer = Agent(
    role="Build Engineer",
    goal="Build the Docker image for the app, push it to ECR, and update the SSM parameter /bluegreen/prod/image_tag so the deploy step can use the new image.",
    backstory="You are a CI/CD build engineer. You run docker build for the app directory, then push the image to ECR using the repo name from SSM or config, and update /bluegreen/prod/image_tag so deployment uses the new tag.",
    tools=[docker_build, ecr_push_and_ssm, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

deploy_engineer = Agent(
    role="Deployment Engineer",
    goal="Trigger the deployment so the new image runs in production. Use CodeDeploy (trigger_codedeploy) when DEPLOY_METHOD=codedeploy or when deploy bundle is in S3; use Ansible (run_ansible_deploy) when DEPLOY_METHOD=ansible. If unset, use DEPLOY_METHOD from environment or describe both options.",
    backstory="You are a deployment engineer. You support two deploy methods: (1) CodeDeploy — trigger_codedeploy with application name, deployment group, s3_bucket and s3_key for the deploy bundle. (2) Ansible — run_ansible_deploy with env (prod/dev), ssm_bucket (from terraform output artifacts_bucket). Check DEPLOY_METHOD env (codedeploy or ansible) to decide which to use; if unset, try ansible if ansible dir exists and ssm_bucket is available, else codedeploy if bundle in S3, else report both options.",
    tools=[trigger_codedeploy, run_ansible_deploy, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)

verifier_agent = Agent(
    role="Deployment Verifier",
    goal="Verify that the production HTTPS health endpoint returns 200 and that SSM parameters /bluegreen/prod/image_tag and /bluegreen/prod/ecr_repo_name are set correctly.",
    backstory="You are a careful DevOps verifier. You use the HTTP health check and SSM read tools to confirm the deployment is live and configured.",
    tools=[http_health_check, read_ssm_parameter],
    verbose=True,
    allow_delegation=False,
)
```

---

### Step 6 — Create `flow.py`

Defines the crew: four tasks in sequence (Infra → Build → Deploy → Verify), with context chained. Calls `set_repo_root(repo_root)` so all tools use that path.

**File: `Multi-Agent-Pipeline/flow.py`**

```python
"""
Multi-Agent Deploy Pipeline: sequential flow Terraform → Build → Deploy → Verify.
"""
from crewai import Crew, Process, Task

from agents import infra_engineer, build_engineer, deploy_engineer, verifier_agent


def create_pipeline_crew(repo_root: str, prod_url: str, aws_region: str) -> Crew:
    """
    Create a crew with four tasks in order:
    1. Infra: Terraform init/plan/(apply if allowed) for bootstrap, dev, prod.
    2. Build: Docker build, ECR push, SSM image_tag update.
    3. Deploy: CodeDeploy or Ansible (via DEPLOY_METHOD).
    4. Verify: HTTP health check and SSM read.
    """
    from tools import set_repo_root
    set_repo_root(repo_root)

    health_url = prod_url.rstrip("/") + "/health" if prod_url else ""

    task_infra = Task(
        description=f"""Run Terraform for the repo at: {repo_root}.

Do in order (only apply if ALLOW_TERRAFORM_APPLY=1):
1. infra/bootstrap: terraform_init("infra/bootstrap"), then terraform_plan("infra/bootstrap"). If ALLOW_TERRAFORM_APPLY=1, terraform_apply("infra/bootstrap").
2. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"). If allowed, terraform_apply("infra/envs/dev", "dev.tfvars").
3. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"). If allowed, terraform_apply("infra/envs/prod", "prod.tfvars").

Summarize: what was planned/applied and any errors. If apply was skipped, say so and remind the user to set ALLOW_TERRAFORM_APPLY=1 to apply.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod: success or failure for each, and whether apply was run or skipped.",
        agent=infra_engineer,
    )

    task_build = Task(
        description=f"""Build the app and push to ECR, then update SSM.

1. Run docker_build(app_relative_path="app", tag=something like a timestamp or "latest"). Use a tag you will pass to ECR.
2. Read the ECR repo name: read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}").
3. Call ecr_push_and_ssm(ecr_repo_name=<from SSM>, image_tag=<tag you used>, aws_region="{aws_region}").

If docker or ECR fails, report the error. Summarize: build OK, push OK, SSM image_tag updated.""",
        expected_output="Summary: Docker build result, ECR push result, SSM /bluegreen/prod/image_tag value set. Or clear error message if a step failed.",
        agent=build_engineer,
        context=[task_infra],
    )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. Choose based on DEPLOY_METHOD (env: codedeploy or ansible).

Option A — CodeDeploy (DEPLOY_METHOD=codedeploy or when bundle is in S3): Call trigger_codedeploy(application_name, deployment_group_name, s3_bucket, s3_key, region="{aws_region}"). Get app name and deployment group from Terraform (e.g. bluegreen-prod, bluegreen-prod-dg). Need deploy bundle uploaded to S3 first.

Option B — Ansible (DEPLOY_METHOD=ansible): Call run_ansible_deploy(env="prod", ssm_bucket=<bucket>, ansible_dir="ansible", region="{aws_region}"). ssm_bucket is the S3 bucket for SSM (get from terraform output -raw artifacts_bucket in infra/envs/prod). Requires ansible/ with inventory and playbooks/deploy.yml in the repo.

If DEPLOY_METHOD is not set, use run_ansible_deploy if ansible directory exists and you can get artifacts_bucket (e.g. from user or terraform output); otherwise use trigger_codedeploy if bundle is in S3; else summarize both options and confirm image_tag from read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").""",
        expected_output="Summary: Deployment triggered via CodeDeploy (with deployment ID) or Ansible (playbook result), or clear instructions for both options and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    task_verify = Task(
        description=f"""Verify the deployment is live and configured.

1. Call http_health_check("{health_url}") to check the production health endpoint.
2. Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").
3. Call read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}").

Summarize: health status (OK or error), image_tag value, ecr_repo_name value, and whether verification passed or failed.""",
        expected_output="Short report: health endpoint status, SSM image_tag, SSM ecr_repo_name, and whether verification passed or failed.",
        agent=verifier_agent,
        context=[task_deploy],
    )

    return Crew(
        agents=[infra_engineer, build_engineer, deploy_engineer, verifier_agent],
        tasks=[task_infra, task_build, task_deploy, task_verify],
        process=Process.sequential,
        verbose=True,
    )
```

---

### Step 7 — Create `run.py`

Entry point: read PROD_URL (env or CLI), REPO_ROOT (default CICD-With-AI when in crew-DevOps), create crew, kickoff, print result.

**File: `Multi-Agent-Pipeline/run.py`**

```python
#!/usr/bin/env python3
"""
Run the Multi-Agent Deploy Pipeline: Terraform → Build → Deploy → Verify.

Usage:
  Set PROD_URL (and optionally AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY), then:
    python run.py
  Or: python run.py https://app.example.com

  REPO_ROOT: path to CICD-With-AI repo. When this folder is in crew-DevOps, default is crew-DevOps/CICD-With-AI.
  ALLOW_TERRAFORM_APPLY=1: allow Terraform apply (default: plan only).
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def main() -> int:
    prod_url = os.environ.get("PROD_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not prod_url:
        print("Usage: PROD_URL=https://app.example.com python run.py")
        print("   or: python run.py https://app.example.com")
        print("Optional: AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY=1")
        return 1

    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    parent_dir = os.path.dirname(_THIS_DIR)
    cicd_path = os.path.join(parent_dir, "CICD-With-AI")
    # Default REPO_ROOT: when in crew-DevOps, use CICD-With-AI next to this folder
    repo_root = os.environ.get("REPO_ROOT") or (cicd_path if os.path.isdir(cicd_path) else parent_dir)

    if not os.path.isdir(repo_root):
        print(f"REPO_ROOT not a directory: {repo_root}")
        return 1

    print(f"Repo root: {repo_root}")
    print(f"Prod URL:  {prod_url}")
    print(f"AWS region: {aws_region}")
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        print("Terraform: plan only (set ALLOW_TERRAFORM_APPLY=1 to allow apply)")
    print()

    from flow import create_pipeline_crew
    crew = create_pipeline_crew(repo_root=repo_root, prod_url=prod_url, aws_region=aws_region)
    result = crew.kickoff()

    print()
    print("--- Pipeline result ---")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### Step 8 — Run the pipeline

From **Multi-Agent-Pipeline** (with CICD-With-AI as sibling when in crew-DevOps):

```bash
cd Multi-Agent-Pipeline
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env: PROD_URL=https://your-prod-url, OPENAI_API_KEY=sk-...
python run.py
```

Or: `python run.py https://your-prod-url`

Optional: set `ALLOW_TERRAFORM_APPLY=1` to allow apply; set `DEPLOY_METHOD=codedeploy` or `DEPLOY_METHOD=ansible` for the deploy step.

---

### Summary (chronological file order)

| Order | File           | Purpose |
|-------|----------------|--------|
| 1     | `requirements.txt` | Python deps (CrewAI, requests, boto3, python-dotenv). |
| 2     | `.env.example` | Template for .env (PROD_URL, AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY, DEPLOY_METHOD, OPENAI_API_KEY). |
| 3     | `.gitignore`   | Ignore .venv, .env, __pycache__, *.pyc. |
| 4     | `tools.py`     | set_repo_root, get_repo_root; Terraform init/plan/apply, docker_build, ecr_push_and_ssm, read_ssm_parameter, run_ansible_deploy, trigger_codedeploy, http_health_check. |
| 5     | `agents.py`    | infra_engineer, build_engineer, deploy_engineer, verifier_agent (each with its tools). |
| 6     | `flow.py`      | create_pipeline_crew(repo_root, prod_url, aws_region): four tasks in order, set_repo_root, return Crew. |
| 7     | `run.py`       | Parse PROD_URL (env/CLI), REPO_ROOT default, create crew, kickoff, print result. |

For **concepts** and **how** it works, see **EXPLANATION.md**. For more setup and commands, see **IMPLEMENTATION.md**.
