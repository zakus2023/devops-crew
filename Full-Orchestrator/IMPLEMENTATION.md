# Full-Orchestrator — Step-by-Step Implementation

This guide gives you the **exact steps**, **commands**, and **full file contents** to set up and run the Full-Orchestrator, and to use the project it generates.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Folder structure](#2-folder-structure)
3. [Step 1: Create virtual environment and install dependencies](#3-step-1-create-virtual-environment-and-install-dependencies)
4. [Step 2: Configure environment and requirements](#4-step-2-configure-environment-and-requirements)
5. [Step 3: Run the orchestrator](#5-step-3-run-the-orchestrator)
6. [Step 4: Run the generated project (after generation)](#6-step-4-run-the-generated-project-after-generation)
7. [Full file contents (reference)](#7-full-file-contents-reference)

---

## 1. Prerequisites

- **Python 3.10+** — Check with: `python --version` or `python3 --version`.
- **Git** — To clone or navigate the repo.
- **Optional:** Terraform and Docker — For the crew to run `terraform validate` and `docker build`; if missing, the crew still generates all files and RUN_ORDER.md.
- **OpenAI API key** — For CrewAI (set in `.env`).

---

## 2. Folder structure

After setup, the Full-Orchestrator folder looks like this:

```
Full-Orchestrator/
├── .env                    # You create from .env.example (do not commit)
├── .env.example            # Example env (commit)
├── requirements.json       # User requirements (commit; edit for your project)
├── requirements.txt        # Python dependencies (commit)
├── run.py                  # Entry point (commit)
├── flow.py                 # Crew and task (commit)
├── agents.py               # Orchestrator agent (commit)
├── tools.py                # Crew tools (commit)
├── generators.py           # File generation logic (commit)
├── EXPLANATION.md          # Beginner explanation (commit)
├── IMPLEMENTATION.md       # This file (commit)
└── output/                 # Created when you run; generated project goes here
    ├── RUN_ORDER.md
    ├── infra/
    │   ├── bootstrap/
    │   ├── modules/platform/
    │   └── envs/dev/ and envs/prod/
    ├── app/
    ├── deploy/
    └── .github/workflows/
```

---

## 3. Step 1: Create virtual environment and install dependencies

**From:** `crew-DevOps/Full-Orchestrator`

```bash
cd Full-Orchestrator

# Create virtual environment
python -m venv .venv

# Activate (Windows Git Bash / CMD)
source .venv/Scripts/activate

# Activate (WSL / Linux / macOS)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**What each dependency does:**

| Package | Why it's there |
|---------|----------------|
| **crewai** | Core framework: defines and runs the orchestrator agent and its tasks (read requirements, generate infra + app, write RUN_ORDER). |
| **crewai-tools** | Provides the `@tool` decorator and tool runtime so the agent can use the custom tools in `tools.py`. |
| **requests** | HTTP client for any tool that makes HTTP calls (e.g. fetch a template, health check). |
| **boto3** | AWS SDK for any tool that talks to AWS (e.g. SSM, S3) during generation or to read/write config. |
| **python-dotenv** | Loads `.env` (e.g. OPENAI_API_KEY, OUTPUT_DIR) so `run.py` can use env vars without exporting them in the shell. |

You should see `(.venv)` in your prompt. If `python` is not found, try `python3` and use `python3 -m venv .venv`.

---

## 4. Step 2: Configure environment and requirements

### 4.1 Create `.env` from `.env.example`

```bash
# Windows (PowerShell)
copy .env.example .env

# WSL / Linux / macOS
cp .env.example .env
```

Edit `.env` and set at least:

```text
OPENAI_API_KEY=sk-your-openai-key-here
```

Optional:

```text
REQUIREMENTS_JSON=./requirements.json
OUTPUT_DIR=./output
```

### 4.2 Edit `requirements.json`

Use the example below and change values to match your AWS account and domains.

**Full `requirements.json` (example):**

```json
{
  "project": "bluegreen",
  "region": "us-east-1",
  "dev": {
    "domain_name": "dev-app.example.com",
    "hosted_zone_id": "Z04241223G31RGIMMIL2C",
    "alarm_email": "dev@example.com",
    "vpc_cidr": "10.20.0.0/16",
    "public_subnets": ["10.20.1.0/24", "10.20.2.0/24"],
    "private_subnets": ["10.20.11.0/24", "10.20.12.0/24"],
    "instance_type": "t3.micro",
    "min_size": 1,
    "max_size": 2,
    "desired_capacity": 1,
    "ami_id": ""
  },
  "prod": {
    "domain_name": "app.example.com",
    "hosted_zone_id": "Z04241223G31RGIMMIL2C",
    "alarm_email": "ops@example.com",
    "vpc_cidr": "10.30.0.0/16",
    "public_subnets": ["10.30.1.0/24", "10.30.2.0/24"],
    "private_subnets": ["10.30.11.0/24", "10.30.12.0/24"],
    "instance_type": "t3.small",
    "min_size": 2,
    "max_size": 6,
    "desired_capacity": 2,
    "ami_id": ""
  }
}
```

Replace:

- `hosted_zone_id` — From Route53 → Hosted zones → your zone ID.
- `domain_name` — Your subdomain (e.g. `dev-app.my-domain.com`).
- `alarm_email` — Email for CloudWatch alarms.

---

## 5. Step 3: Run the orchestrator

**From:** `Full-Orchestrator` (with venv activated and `.env` set)

```bash
# Default: uses ./requirements.json and writes to ./output
python run.py
```

**With custom paths:**

```bash
python run.py /path/to/my-requirements.json --output-dir ./my-output
```

Or set env and run:

```bash
set REQUIREMENTS_JSON=./my-reqs.json
set OUTPUT_DIR=./my-output
python run.py
```

**What happens:**

1. `run.py` loads the requirements and creates the output directory.
2. It builds a CrewAI crew with one agent and one task (generate → validate → write RUN_ORDER).
3. The agent calls the generation tools in order, then validation tools, then writes RUN_ORDER.md.
4. You see a summary and the path to the generated project.

**Expected output (summary):**

```text
Output directory: C:\...\Full-Orchestrator\output
Starting Full-Orchestrator crew...
...
--- Full-Orchestrator result ---
[Agent summary: generated bootstrap, platform, dev, prod, app, deploy, workflows; validation results; RUN_ORDER.md written.]
Generated project is in: C:\...\Full-Orchestrator\output
Next: follow RUN_ORDER.md in that directory.
```

---

## 6. Step 4: Run the generated project (after generation)

After the crew finishes, **from the generated project root** (e.g. `Full-Orchestrator/output`):

### 6.1 Bootstrap (once)

```bash
cd infra/bootstrap
terraform init
terraform apply -auto-approve
```

Then copy outputs:

```bash
terraform output
```

Update:

- `infra/envs/dev/backend.hcl` — Set `bucket`, `dynamodb_table`, `region` from outputs.
- `infra/envs/prod/backend.hcl` — Same.
- `infra/envs/dev/dev.tfvars` — Set `cloudtrail_bucket` from bootstrap output.
- `infra/envs/prod/prod.tfvars` — Same.

### 6.2 Dev environment

```bash
cd infra/envs/dev
terraform init -backend-config=backend.hcl -reconfigure
terraform apply -auto-approve -var-file=dev.tfvars
```

### 6.3 Prod environment

```bash
cd infra/envs/prod
terraform init -backend-config=backend.hcl -reconfigure
terraform apply -auto-approve -var-file=prod.tfvars
```


### 6.4 Optional bastion host (SSH to private instances)

If you use **DEPLOY_METHOD=ssh_script** (e.g. from Multi-Agent-Pipeline) and your app instances are in **private subnets**, you can enable an optional bastion so your local machine can SSH via ProxyJump (local → bastion → instance).

1. **Create an EC2 key pair** in AWS (EC2 → Key pairs) if you do not have one. Use the same key for the bastion and for SSH deploy (e.g. `test-ai-ec2-key`).
2. **Edit** `infra/envs/prod/prod.tfvars` (and `infra/envs/dev/dev.tfvars` if you want a dev bastion): set `enable_bastion = true`, `key_name = "YOUR_AWS_KEY_PAIR_NAME"` (must match the key pair name in AWS and your `.pem`), and optionally `allowed_bastion_cidr = "YOUR_IP/32"`.
3. **Apply** (or re-apply): from `infra/envs/prod` run `terraform apply -auto-approve -var-file=prod.tfvars`.
4. **In the pipeline** (Multi-Agent-Pipeline): set **DEPLOY_METHOD=ssh_script** and **SSH_KEY_PATH** (path to your `.pem`). You can **leave BASTION_HOST unset**—the pipeline auto-reads `bastion_public_ip` from Terraform output (`infra/envs/prod` or `infra/envs/dev`), so you do not need to update `.env` when the bastion IP changes (e.g. after stop/start). Optionally set **BASTION_HOST** to override, and **BASTION_USER=ec2-user** if needed.

Generated `prod.tfvars` and `dev.tfvars` include `enable_bastion = false`, `key_name = ""`, `allowed_bastion_cidr = "0.0.0.0/0"`; change them as above to enable the bastion.

### 6.5 OIDC and GitHub Actions

Create the OIDC IAM role for your GitHub repo (see CICD-With-AI's RUN_COMMANDS_ORDER.md §3a), then add repo secrets: `AWS_ROLE_TO_ASSUME`, `AWS_REGION`.

### 6.6 Build and deploy

Push to `main`; workflows under `.github/workflows/` run on path filters (e.g. `app/**` for build-push). Then run CodeDeploy or Ansible per your setup.

### 6.7 Teardown (destroy resources)

From the generated project root, destroy in reverse order (prod → dev → bootstrap):

```bash
cd infra/envs/prod
terraform destroy -auto-approve -var-file=prod.tfvars

cd ../dev
terraform destroy -auto-approve -var-file=dev.tfvars

cd ../../bootstrap
terraform destroy -auto-approve
```

---

## 7. Full file contents (reference)

Below are the **full contents** of the key files in the Full-Orchestrator and of the **generated** files so you can recreate or compare.

### 7.1 `run.py`

```python
#!/usr/bin/env python3
"""
Run the Full-Orchestrator: generate infra + app from requirements and validate.

Usage:
  python run.py [--output-dir DIR] [requirements.json]
  Or set REQUIREMENTS_JSON and OUTPUT_DIR in environment (or .env).

If no requirements file is given, uses requirements.json in this directory.
Output directory defaults to ./output (created if missing).
"""
import argparse
import json
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


def load_requirements(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-Orchestrator: generate infra/app from requirements")
    parser.add_argument("requirements_file", nargs="?", default=None, help="Path to requirements.json")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for generated project")
    args = parser.parse_args()

    requirements_path = args.requirements_file or os.environ.get("REQUIREMENTS_JSON") or os.path.join(_THIS_DIR, "requirements.json")
    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR") or os.path.join(_THIS_DIR, "output")

    if not os.path.isfile(requirements_path):
        print(f"Requirements file not found: {requirements_path}")
        print("Create requirements.json or pass path. See requirements.json.example.")
        return 1

    requirements = load_requirements(requirements_path)
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {os.path.abspath(output_dir)}")
    print("Starting Full-Orchestrator crew...")
    print()

    from flow import create_orchestrator_crew
    crew = create_orchestrator_crew(output_dir=output_dir, requirements=requirements)
    result = crew.kickoff()

    print()
    print("--- Full-Orchestrator result ---")
    print(result)
    print()
    print(f"Generated project is in: {os.path.abspath(output_dir)}")
    print("Next: follow RUN_ORDER.md in that directory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 7.2 `flow.py`

```python
"""
Crew flow: one orchestrator agent, one task to generate and validate from requirements.
"""
from crewai import Crew, Process, Task

from agents import create_orchestrator_agent
from tools import create_orchestrator_tools


def create_orchestrator_crew(output_dir: str, requirements: dict) -> Crew:
    tools = create_orchestrator_tools(output_dir, requirements)
    agent = create_orchestrator_agent(tools)

    task = Task(
        description=f"""Generate the full deployment project into the output directory: {output_dir}.

Do the following in order:

1. Generate Terraform bootstrap: call the generate_bootstrap tool.
2. Generate platform module: call the generate_platform tool.
3. Generate dev environment: call the generate_dev_env tool.
4. Generate prod environment: call the generate_prod_env tool.
5. Generate app (Node.js + Dockerfile): call the generate_app tool.
6. Generate deploy bundle (appspec + scripts): call the generate_deploy tool.
7. Generate GitHub Actions workflows: call the generate_workflows tool.

8. Validate: run terraform validate in infra/bootstrap, then infra/envs/dev, then infra/envs/prod. If Terraform is not installed, report that and continue.
9. Validate: run docker build in the app directory. If Docker is not installed, report that and continue.
10. Write the run order: call the tool_write_run_order tool with a short summary of what was generated and any notes (e.g. "Fill backend.hcl and tfvars with bootstrap outputs before running dev/prod apply").

Summarize at the end: list what was generated, which validations passed or were skipped, and where the user should look (RUN_ORDER.md) for the exact commands to run next.""",
        expected_output="A clear summary: (1) All generated components listed, (2) Terraform and Docker validation results, (3) Pointer to RUN_ORDER.md and the recommended next steps for the user.",
        agent=agent,
    )

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
```

### 7.3 `agents.py`

```python
"""
Orchestrator agent: generates full infra + app from requirements and validates.
"""
from crewai import Agent


def create_orchestrator_agent(tools: list) -> Agent:
    return Agent(
        role="Full Stack DevOps Orchestrator",
        goal="Generate a complete deployment project (Terraform bootstrap, platform module, dev/prod envs, Node.js app, CodeDeploy bundle, GitHub Actions) from user requirements, then validate Terraform and Docker and write a RUN_ORDER.md with the exact command sequence for the user.",
        backstory="You are an expert DevOps engineer. You take a structured requirements input and produce a full, runnable repo: infrastructure as code, application code, deploy scripts, and CI workflows. You always generate components in the correct order (bootstrap first, then platform module, then dev then prod envs, then app and deploy and workflows), then run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod, and docker build in app, and finally write RUN_ORDER.md so the user knows the exact steps to run.",
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )
```

### 7.4 Generated: `infra/bootstrap/main.tf` (representative)

The generator writes bootstrap Terraform equivalent to:

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_kms_key" "tfstate" {
  description             = "${var.project} terraform state key"
  deletion_window_in_days = 10
  enable_key_rotation     = true
}

resource "aws_s3_bucket" "tfstate" {
  bucket_prefix = "${var.project}-tfstate-"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tfstate.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tflock" {
  name         = "${var.project}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

resource "aws_s3_bucket" "cloudtrail" {
  bucket_prefix = "${var.project}-cloudtrail-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

### 7.5 Generated: `app/package.json`

```json
{
  "name": "bluegreen-sample",
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.19.2"
  }
}
```

### 7.6 Generated: `app/server.js`

```javascript
const express = require("express");
const os = require("os");

const app = express();
const port = process.env.PORT || 8080;

app.get("/health", (_req, res) => {
  res.status(200).send("OK");
});

app.get("/", (_req, res) => {
  res.json({
    message: "Hello from Blue/Green deployment (HTTPS)",
    hostname: os.hostname(),
    version: process.env.APP_VERSION || "dev",
    timestamp: new Date().toISOString(),
  });
});

app.listen(port, () => {
  console.log(`Server listening on ${port}`);
});
```

### 7.7 Generated: `app/Dockerfile`

```dockerfile
FROM node:20-alpine

WORKDIR /usr/src/app

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm i --omit=dev

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["npm", "start"]
```

### 7.8 Generated: `deploy/appspec.yml`

```yaml
version: 0.0
os: linux

files:
  - source: /
    destination: /opt/codedeploy-bluegreen
    overwrite: true

hooks:
  ApplicationStop:
    - location: scripts/stop.sh
      timeout: 300
      runas: root
  BeforeInstall:
    - location: scripts/install.sh
      timeout: 600
      runas: root
  ApplicationStart:
    - location: scripts/start.sh
      timeout: 600
      runas: root
  ValidateService:
    - location: scripts/validate.sh
      timeout: 300
      runas: root
```

### 7.9 Generated: `deploy/scripts/install.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
systemctl enable docker || true
systemctl start docker || true
mkdir -p /opt/codedeploy-bluegreen
```

### 7.10 Generated: `deploy/scripts/stop.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
docker stop bluegreen-app 2>/dev/null || true
docker rm bluegreen-app 2>/dev/null || true
```

### 7.11 Generated: `deploy/scripts/start.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
REGION=$(aws configure get region || echo us-east-1)
IMAGE_TAG=$(aws ssm get-parameter --name "/bluegreen/prod/image_tag" --query "Parameter.Value" --output text 2>/dev/null || echo "latest")
ECR_REPO=$(aws ssm get-parameter --name "/bluegreen/prod/ecr_repo_name" --query "Parameter.Value" --output text 2>/dev/null || echo "bluegreen-prod-app")
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker pull ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
docker run -d --name bluegreen-app -p 8080:8080 --restart unless-stopped ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
```

### 7.12 Generated: `deploy/scripts/validate.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf http://localhost:8080/health || exit 1
```

### 7.13 Generated: `.github/workflows/build-push.yml` (representative)

```yaml
name: Build and Push Image
on:
  push:
    branches: [main]
    paths: ["app/**"]
permissions:
  id-token: write
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ secrets.AWS_REGION }}
      - name: Get ECR repo
        id: ssm
        run: |
          ECR_REPO=$(aws ssm get-parameter --name "/bluegreen/prod/ecr_repo_name" --query "Parameter.Value" --output text)
          echo "ecr_repo_name=$ECR_REPO" >> $GITHUB_OUTPUT
      - uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push
        env:
          ECR_REPO_NAME: ${{ steps.ssm.outputs.ecr_repo_name }}
          AWS_REGION: ${{ secrets.AWS_REGION }}
        run: |
          TAG=${GITHUB_SHA::12}
          ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
          ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
          docker build -t "${ECR_REPO_NAME}:${TAG}" app
          docker tag "${ECR_REPO_NAME}:${TAG}" "${ECR_URI}:${TAG}"
          docker push "${ECR_URI}:${TAG}"
          aws ssm put-parameter --name "/bluegreen/prod/image_tag" --value "$TAG" --type String --overwrite --region $AWS_REGION
```

### 7.14 Platform module (and optional bastion)

If **crew-DevOps/infra/modules/platform** (or the repo’s equivalent path) exists, the Full-Orchestrator **copies** the full platform module from there into the generated project. That module includes VPC, ALB, ASG, ECR, CodeDeploy, alarms, and an **optional bastion host** (see [§6.4 Optional bastion host](#64-optional-bastion-host-ssh-to-private-instances)). Generated **prod.tfvars** and **dev.tfvars** include `enable_bastion`, `key_name`, and `allowed_bastion_cidr`; set them and re-apply to create the bastion and use `bastion_public_ip` (e.g. as **BASTION_HOST** in the pipeline). If the platform source directory does not exist, the orchestrator writes a minimal placeholder (SSM only); add the full module from the repo and re-run to get the full platform.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Create venv and `pip install -r requirements.txt` |
| 2 | Copy `.env.example` to `.env`, set `OPENAI_API_KEY`; edit `requirements.json` |
| 3 | Run `python run.py` (or with custom requirements path and `--output-dir`) |
| 4 | Follow `RUN_ORDER.md` in the output directory: bootstrap → dev → prod → (optional bastion) → OIDC → build/deploy |

For **concepts** and **why** the orchestrator works this way, see **EXPLANATION.md**.
