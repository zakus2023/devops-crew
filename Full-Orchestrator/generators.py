"""
Generate infra, app, deploy, and workflow files from a requirements dict.
Used by the Full-Orchestrator crew tools. All paths are relative to output_dir.
"""

import os       # Paths (dirname, join) and creating directories (makedirs).
import json     # Serialize lists/dicts to JSON strings for tfvars and package.json.
import shutil   # Copy app directory (binary-safe copy2).
from typing import Any, Dict   # Type hints for the requirements dict and return values.


def _ensure_dir(file_path: str) -> None:
    """Create the directory for file_path if it doesn't exist (e.g. infra/bootstrap for infra/bootstrap/main.tf)."""
    d = os.path.dirname(file_path)   # e.g. "infra/bootstrap" from "infra/bootstrap/main.tf"
    if d:
        os.makedirs(d, exist_ok=True)   # exist_ok=True: don't error if dir already exists


def _write(path: str, content: str, output_dir: str) -> None:
    """Write content to output_dir/path. Creates parent directories as needed."""
    full = os.path.join(output_dir, path)   # e.g. ./output/infra/bootstrap/main.tf
    _ensure_dir(full)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def _get(req: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Safely get a nested value from requirements, e.g. _get(req, 'dev', 'domain_name') -> dev.domain_name or default."""
    d = req
    for k in keys:
        d = d.get(k, {}) if isinstance(d, dict) else default   # If not a dict (e.g. None), return default
        if d is None:
            return default
    return d if d != {} else default   # Empty dict from .get(k, {}) means key missing -> return default


def generate_bootstrap(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate Terraform bootstrap (S3 state bucket, DynamoDB lock, KMS, CloudTrail bucket)."""
    project = _get(requirements, "project") or "bluegreen"
    region = _get(requirements, "region") or "us-east-1"
    # variables.tf: project and region (used in resource names and provider).
    _write("infra/bootstrap/variables.tf", f'''variable "project" {{
  type    = string
  default = "{project}"
}}

variable "region" {{
  type    = string
  default = "{region}"
}}
''', output_dir)
    # main.tf: Terraform + AWS provider, KMS key, S3 state bucket (versioning, encryption, public block), DynamoDB lock, CloudTrail bucket.
    _write("infra/bootstrap/main.tf", f'''terraform {{
  required_version = ">= 1.6.0"
  required_providers {{
    aws = {{ source = "hashicorp/aws", version = ">= 5.0" }}
  }}
}}

provider "aws" {{
  region = var.region
}}

resource "aws_kms_key" "tfstate" {{
  description             = "${{var.project}} terraform state key"
  deletion_window_in_days = 10
  enable_key_rotation     = true
}}

resource "aws_s3_bucket" "tfstate" {{
  bucket_prefix = "${{var.project}}-tfstate-"
  force_destroy = true
}}

resource "aws_s3_bucket_versioning" "tfstate" {{
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {{
    status = "Enabled"
  }}
}}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {{
  bucket = aws_s3_bucket.tfstate.id
  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tfstate.arn
    }}
  }}
}}

resource "aws_s3_bucket_public_access_block" "tfstate" {{
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}}

resource "aws_dynamodb_table" "tflock" {{
  name         = "${{var.project}}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {{
    name = "LockID"
    type = "S"
  }}
}}

resource "aws_s3_bucket" "cloudtrail" {{
  bucket_prefix = "${{var.project}}-cloudtrail-"
  force_destroy = true
}}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {{
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}}
''', output_dir)
    # outputs.tf: values needed by envs (backend bucket, lock table, KMS ARN, cloudtrail bucket).
    _write("infra/bootstrap/outputs.tf", '''output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "tflock_table" {
  value = aws_dynamodb_table.tflock.name
}

output "tfstate_kms" {
  value = aws_kms_key.tfstate.arn
}

output "cloudtrail_bucket" {
  value = aws_s3_bucket.cloudtrail.bucket
}
''', output_dir)
    return f"Bootstrap Terraform written to {output_dir}/infra/bootstrap (variables.tf, main.tf, outputs.tf)"


def generate_platform(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate platform Terraform module. If crew-DevOps/infra/modules/platform exists, copy full module from there; else write minimal placeholder."""
    # Resolve crew-DevOps root: this file is Full-Orchestrator/generators.py, so parent of parent = crew-DevOps.
    _this_file = os.path.abspath(__file__)
    _full_orchestrator_dir = os.path.dirname(_this_file)
    _crew_devops_root = os.path.dirname(_full_orchestrator_dir)
    _platform_source = os.path.join(_crew_devops_root, "infra", "modules", "platform")

    out_platform = os.path.join(output_dir, "infra", "modules", "platform")
    if os.path.isdir(_platform_source):
        # Copy all .tf files from crew-DevOps/infra/modules/platform into output.
        os.makedirs(out_platform, exist_ok=True)
        for name in os.listdir(_platform_source):
            if name.endswith(".tf"):
                src = os.path.join(_platform_source, name)
                if os.path.isfile(src):
                    with open(src, "r", encoding="utf-8") as f:
                        content = f.read()
                    _write(f"infra/modules/platform/{name}", content, output_dir)
        return f"Platform module copied from crew-DevOps/infra/modules/platform to {output_dir}/infra/modules/platform"

    # Fallback: write minimal placeholder (SSM only).
    project = _get(requirements, "project") or "bluegreen"
    _write("infra/modules/platform/variables.tf", f'''variable "project" {{ type = string }}
variable "region" {{ type = string }}
variable "env" {{ type = string }}
variable "domain_name" {{ type = string }}
variable "hosted_zone_id" {{ type = string }}
variable "alarm_email" {{ type = string }}
variable "vpc_cidr" {{ type = string }}
variable "public_subnets" {{ type = list(string) }}
variable "private_subnets" {{ type = list(string) }}
variable "instance_type" {{ type = string }}
variable "min_size" {{ type = number }}
variable "max_size" {{ type = number }}
variable "desired_capacity" {{ type = number }}
variable "ami_id" {{ type = string }}
variable "cloudtrail_bucket" {{ type = string }}
variable "enable_guardduty" {{ type = bool }}
variable "enable_securityhub" {{ type = bool }}
variable "enable_inspector2" {{ type = bool }}
variable "enable_config" {{ type = bool }}
variable "enable_deployment_alarms" {{ type = bool }}
''', output_dir)
    # Fallback: minimal platform (SSM only). Add full .tf files in crew-DevOps/infra/modules/platform and re-run to copy.
    _write("infra/modules/platform/main.tf", f'''# Platform module for ${{var.project}}-${{var.env}}
# Placeholder: crew-DevOps/infra/modules/platform not found. Add full platform .tf files there and re-run to copy.

terraform {{
  required_version = ">= 1.6.0"
  required_providers {{
    aws = {{ source = "hashicorp/aws", version = ">= 5.0" }}
    null = {{ source = "hashicorp/null", version = ">= 3.0" }}
  }}
}}

resource "aws_ssm_parameter" "image_tag" {{
  name  = "/${{var.project}}/${{var.env}}/image_tag"
  type  = "String"
  value = "initial"
}}

resource "aws_ssm_parameter" "ecr_repo_name" {{
  name  = "/${{var.project}}/${{var.env}}/ecr_repo_name"
  type  = "String"
  value = "${{var.project}}-${{var.env}}-app"
}}
''', output_dir)
    _write("infra/modules/platform/outputs.tf", '''output "ecr_repo_name" { value = aws_ssm_parameter.ecr_repo_name.value }
output "https_url" { value = "https://placeholder.example.com" }
''', output_dir)
    return f"Platform module written to {output_dir}/infra/modules/platform (minimal; add full module in crew-DevOps/infra/modules/platform and re-run to copy)"


def generate_dev_env(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate dev environment Terraform (main.tf, variables, outputs, backend.hcl, dev.tfvars)."""
    project = _get(requirements, "project") or "bluegreen"
    region = _get(requirements, "region") or "us-east-1"
    dev = _get(requirements, "dev") or {}
    # Pull all dev.* values from requirements with sensible defaults.
    domain = _get(dev, "domain_name") or "dev-app.example.com"
    zone_id = _get(dev, "hosted_zone_id") or "Z000000000000"
    alarm_email = _get(dev, "alarm_email") or "dev@example.com"
    vpc_cidr = _get(dev, "vpc_cidr") or "10.20.0.0/16"
    pub = _get(dev, "public_subnets")
    if not pub:
        pub = ["10.20.1.0/24", "10.20.2.0/24"]
    priv = _get(dev, "private_subnets")
    if not priv:
        priv = ["10.20.11.0/24", "10.20.12.0/24"]
    instance_type = _get(dev, "instance_type") or "t3.micro"
    min_s = _get(dev, "min_size") or 1
    max_s = _get(dev, "max_size") or 2
    desired = _get(dev, "desired_capacity") or 1
    ami_id = _get(dev, "ami_id") or ""

    _write("infra/envs/dev/main.tf", f'''terraform {{
  required_version = ">= 1.6.0"
  required_providers {{
    aws = {{ source = "hashicorp/aws", version = ">= 5.0" }}
    null = {{ source = "hashicorp/null", version = ">= 3.0" }}
  }}
  backend "s3" {{}}
}}

provider "aws" {{
  region = var.region
}}

module "platform" {{
  source = "../../modules/platform"
  project        = var.project
  region         = var.region
  env            = "dev"
  domain_name    = var.domain_name
  hosted_zone_id = var.hosted_zone_id
  alarm_email    = var.alarm_email
  vpc_cidr       = var.vpc_cidr
  public_subnets = var.public_subnets
  private_subnets = var.private_subnets
  instance_type    = var.instance_type
  min_size         = var.min_size
  max_size         = var.max_size
  desired_capacity = var.desired_capacity
  ami_id           = var.ami_id
  cloudtrail_bucket = var.cloudtrail_bucket
  enable_guardduty  = var.enable_guardduty
  enable_securityhub = var.enable_securityhub
  enable_inspector2 = var.enable_inspector2
  enable_config     = var.enable_config
  enable_deployment_alarms = var.enable_deployment_alarms
}}
''', output_dir)
    # variables.tf: same shape as module inputs (project, region, domain, VPC, instance, etc.).
    _write("infra/envs/dev/variables.tf", '''variable "project" { type = string }
variable "region" { type = string }
variable "domain_name" { type = string }
variable "hosted_zone_id" { type = string }
variable "alarm_email" { type = string }
variable "vpc_cidr" { type = string }
variable "public_subnets" { type = list(string) }
variable "private_subnets" { type = list(string) }
variable "instance_type" { type = string }
variable "min_size" { type = number }
variable "max_size" { type = number }
variable "desired_capacity" { type = number }
variable "ami_id" { type = string }
variable "cloudtrail_bucket" { type = string }
variable "enable_guardduty" { type = bool }
variable "enable_securityhub" { type = bool }
variable "enable_inspector2" { type = bool }
variable "enable_config" { type = bool }
variable "enable_deployment_alarms" { type = bool }
''', output_dir)
    _write("infra/envs/dev/outputs.tf", 'output "https_url" { value = module.platform.https_url }\n', output_dir)
    # backend.hcl: user fills bucket/dynamodb_table from bootstrap outputs before init.
    _write("infra/envs/dev/backend.hcl", '''# Fill bucket, key, dynamodb_table after bootstrap apply
bucket         = "YOUR_TFSTATE_BUCKET"
key            = "dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "YOUR_TFLOCK_TABLE"
encrypt        = true
''', output_dir)
    # dev.tfvars: values for this run (project, region, domain, subnets, instance, ami_id, cloudtrail/guardrails).
    pub_s = json.dumps(pub)
    priv_s = json.dumps(priv)
    _write("infra/envs/dev/dev.tfvars", f'''project = "{project}"
region  = "{region}"
domain_name    = "{domain}"
hosted_zone_id = "{zone_id}"
alarm_email    = "{alarm_email}"
cloudtrail_bucket = "YOUR_CLOUDTRAIL_BUCKET"
vpc_cidr       = "{vpc_cidr}"
public_subnets = {pub_s}
private_subnets = {priv_s}
instance_type    = "{instance_type}"
min_size         = {min_s}
max_size         = {max_s}
desired_capacity = {desired}
ami_id = "{ami_id}"
enable_deployment_alarms = false
enable_guardduty = true
enable_securityhub = true
enable_inspector2 = true
enable_config = true
''', output_dir)
    return f"Dev environment written to {output_dir}/infra/envs/dev"


def generate_prod_env(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate prod environment Terraform (same structure as dev; prod.tfvars, backend.hcl)."""
    project = _get(requirements, "project") or "bluegreen"
    region = _get(requirements, "region") or "us-east-1"
    prod = _get(requirements, "prod") or {}
    domain = _get(prod, "domain_name") or "app.example.com"
    zone_id = _get(prod, "hosted_zone_id") or "Z000000000000"
    alarm_email = _get(prod, "alarm_email") or "ops@example.com"
    vpc_cidr = _get(prod, "vpc_cidr") or "10.30.0.0/16"
    pub = _get(prod, "public_subnets") or ["10.30.1.0/24", "10.30.2.0/24"]
    priv = _get(prod, "private_subnets") or ["10.30.11.0/24", "10.30.12.0/24"]
    instance_type = _get(prod, "instance_type") or "t3.small"
    min_s = _get(prod, "min_size") or 2
    max_s = _get(prod, "max_size") or 6
    desired = _get(prod, "desired_capacity") or 2
    ami_id = _get(prod, "ami_id") or ""

    # Same layout as dev: main.tf (backend + module), variables.tf, outputs.tf, backend.hcl, prod.tfvars.
    _write("infra/envs/prod/main.tf", f'''terraform {{
  required_version = ">= 1.6.0"
  required_providers {{
    aws = {{ source = "hashicorp/aws", version = ">= 5.0" }}
    null = {{ source = "hashicorp/null", version = ">= 3.0" }}
  }}
  backend "s3" {{}}
}}

provider "aws" {{
  region = var.region
}}

module "platform" {{
  source = "../../modules/platform"
  project        = var.project
  region         = var.region
  env            = "prod"
  domain_name    = var.domain_name
  hosted_zone_id = var.hosted_zone_id
  alarm_email    = var.alarm_email
  vpc_cidr       = var.vpc_cidr
  public_subnets = var.public_subnets
  private_subnets = var.private_subnets
  instance_type    = var.instance_type
  min_size         = var.min_size
  max_size         = var.max_size
  desired_capacity = var.desired_capacity
  ami_id           = var.ami_id
  cloudtrail_bucket = var.cloudtrail_bucket
  enable_guardduty  = var.enable_guardduty
  enable_securityhub = var.enable_securityhub
  enable_inspector2 = var.enable_inspector2
  enable_config     = var.enable_config
  enable_deployment_alarms = var.enable_deployment_alarms
}}
''', output_dir)
    _write("infra/envs/prod/variables.tf", '''variable "project" { type = string }
variable "region" { type = string }
variable "domain_name" { type = string }
variable "hosted_zone_id" { type = string }
variable "alarm_email" { type = string }
variable "vpc_cidr" { type = string }
variable "public_subnets" { type = list(string) }
variable "private_subnets" { type = list(string) }
variable "instance_type" { type = string }
variable "min_size" { type = number }
variable "max_size" { type = number }
variable "desired_capacity" { type = number }
variable "ami_id" { type = string }
variable "cloudtrail_bucket" { type = string }
variable "enable_guardduty" { type = bool }
variable "enable_securityhub" { type = bool }
variable "enable_inspector2" { type = bool }
variable "enable_config" { type = bool }
variable "enable_deployment_alarms" { type = bool }
''', output_dir)
    _write("infra/envs/prod/outputs.tf", 'output "https_url" { value = module.platform.https_url }\n', output_dir)
    _write("infra/envs/prod/backend.hcl", '''bucket         = "YOUR_TFSTATE_BUCKET"
key            = "prod/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "YOUR_TFLOCK_TABLE"
encrypt        = true
''', output_dir)
    pub_s = json.dumps(pub)
    priv_s = json.dumps(priv)
    _write("infra/envs/prod/prod.tfvars", f'''project = "{project}"
region  = "{region}"
domain_name    = "{domain}"
hosted_zone_id = "{zone_id}"
alarm_email    = "{alarm_email}"
cloudtrail_bucket = "YOUR_CLOUDTRAIL_BUCKET"
vpc_cidr       = "{vpc_cidr}"
public_subnets = {pub_s}
private_subnets = {priv_s}
instance_type    = "{instance_type}"
min_size         = {min_s}
max_size         = {max_s}
desired_capacity = {desired}
ami_id = "{ami_id}"
enable_deployment_alarms = true
enable_guardduty = true
enable_securityhub = true
enable_inspector2 = true
enable_config = true
''', output_dir)
    return f"Prod environment written to {output_dir}/infra/envs/prod"


def _copy_app_from_dir(app_source_dir: str, output_dir: str) -> None:
    """Copy app files from app_source_dir into output_dir/app (files and subdirs like public/). Skips node_modules, .git, .env."""
    out_app = os.path.join(output_dir, "app")
    os.makedirs(out_app, exist_ok=True)
    for name in os.listdir(app_source_dir):
        src = os.path.join(app_source_dir, name)
        if name in (".git", "node_modules", ".env"):
            continue
        dst = os.path.join(out_app, name)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "node_modules", ".env"), dirs_exist_ok=True)


def generate_app(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate or copy app. Source (in order): APP_PATH env, requirements app_path, crew-DevOps/app if present, else default generated app."""
    # Resolve app source: .env APP_PATH > requirements app_path > crew-DevOps/app if exists > None (use default).
    app_source = os.environ.get("APP_PATH") or _get(requirements, "app_path") or None
    if not app_source or not os.path.isdir(app_source):
        _this_file = os.path.abspath(__file__)
        _crew_devops_root = os.path.dirname(os.path.dirname(_this_file))
        crew_devops_app = os.path.join(_crew_devops_root, "app")
        if os.path.isdir(crew_devops_app):
            app_source = crew_devops_app
        else:
            app_source = None
    if app_source and os.path.isdir(app_source):
        _copy_app_from_dir(app_source, output_dir)
        return f"App copied from {app_source} to {output_dir}/app"
    # Default: generate sample app in output.
    project = _get(requirements, "project") or "bluegreen"
    _write("app/package.json", json.dumps({
        "name": f"{project}-sample",
        "main": "server.js",
        "scripts": {"start": "node server.js"},
        "dependencies": {"express": "^4.19.2"}
    }, indent=2), output_dir)
    _write("app/server.js", '''const express = require("express");
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
''', output_dir)
    _write("app/Dockerfile", '''FROM node:20-alpine

WORKDIR /usr/src/app

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm i --omit=dev

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["npm", "start"]
''', output_dir)
    return f"App written to {output_dir}/app (default: package.json, server.js, Dockerfile)"


def generate_deploy(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate CodeDeploy bundle (appspec + scripts) and Ansible deploy (inventory + playbook). Deploy option: CodeDeploy or Ansible via DEPLOY_METHOD."""
    project = _get(requirements, "project") or "bluegreen"
    region = _get(requirements, "region") or "us-east-1"
    # --- CodeDeploy: appspec + scripts ---
    _write("deploy/appspec.yml", '''version: 0.0
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
''', output_dir)
    # install.sh: enable/start docker, create app dir.
    _write("deploy/scripts/install.sh", '''#!/usr/bin/env bash
set -euo pipefail
systemctl enable docker || true
systemctl start docker || true
mkdir -p /opt/codedeploy-bluegreen
''', output_dir)
    # stop.sh: stop and remove existing container so start can run a new one.
    _write("deploy/scripts/stop.sh", '''#!/usr/bin/env bash
set -euo pipefail
docker stop bluegreen-app 2>/dev/null || true
docker rm bluegreen-app 2>/dev/null || true
''', output_dir)
    # start.sh: read image_tag and ecr_repo_name from SSM, pull image, run container on 8080.
    _write("deploy/scripts/start.sh", '''#!/usr/bin/env bash
set -euo pipefail
REGION=$(aws configure get region || echo us-east-1)
IMAGE_TAG=$(aws ssm get-parameter --name "/bluegreen/prod/image_tag" --query "Parameter.Value" --output text 2>/dev/null || echo "latest")
ECR_REPO=$(aws ssm get-parameter --name "/bluegreen/prod/ecr_repo_name" --query "Parameter.Value" --output text 2>/dev/null || echo "bluegreen-prod-app")
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker pull ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
docker run -d --name bluegreen-app -p 8080:8080 --restart unless-stopped ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
''', output_dir)
    # validate.sh: curl localhost:8080/health; exit 1 if unhealthy (CodeDeploy marks deployment failed).
    _write("deploy/scripts/validate.sh", '''#!/usr/bin/env bash
set -euo pipefail
curl -sf http://localhost:8080/health || exit 1
''', output_dir)

    # --- Ansible: inventory + playbook (option for DEPLOY_METHOD=ansible; no dependency on CICD-With-AI) ---
    _write("ansible/requirements.yml", '''# Install: ansible-galaxy collection install -r ansible/requirements.yml
collections:
  - name: amazon.aws
    version: ">=5.0"
  - name: community.aws
    version: ">=4.0"
''', output_dir)
    _write("ansible/inventory/ec2_dev.aws_ec2.yml", f'''# EC2 dynamic inventory for dev. Use: -i inventory/ec2_dev.aws_ec2.yml
plugin: amazon.aws.aws_ec2
regions:
  - {region}
hostnames:
  - instance-id
filters:
  instance-state-name: running
  tag:Env: dev
keyed_groups:
  - key: tags.Env
    prefix: env
''', output_dir)
    _write("ansible/inventory/ec2_prod.aws_ec2.yml", f'''# EC2 dynamic inventory for prod. Use: -i inventory/ec2_prod.aws_ec2.yml
plugin: amazon.aws.aws_ec2
regions:
  - {region}
hostnames:
  - instance-id
filters:
  instance-state-name: running
  tag:Env: prod
keyed_groups:
  - key: tags.Env
    prefix: env
''', output_dir)
    _write("ansible/playbooks/deploy.yml", '''---
# Deploy app to EC2 via SSM (no SSH). Use with pipeline DEPLOY_METHOD=ansible.
# From repo root: ansible-playbook -i ansible/inventory/ec2_prod.aws_ec2.yml ansible/playbooks/deploy.yml -e ssm_bucket=BUCKET -e env=prod
# Get bucket: terraform output -raw artifacts_bucket (from infra/envs/prod or dev)
- name: Deploy app (pull ECR image, run container)
  hosts: all
  gather_facts: false
  connection: community.aws.aws_ssm
  become: true
  vars:
    deploy_env: "{{ env | default('dev') }}"
    ansible_aws_ssm_bucket_name: "{{ ssm_bucket }}"
    ansible_aws_ssm_region: "{{ ssm_region | default('us-east-1') }}"
  tasks:
    - name: Require ssm_bucket
      ansible.builtin.assert:
        that: ssm_bucket is defined and ssm_bucket | length > 0
        fail_msg: "Pass -e ssm_bucket=BUCKET (from terraform output -raw artifacts_bucket)"
      tags: always
    - name: Stop existing container
      ansible.builtin.shell: docker rm -f bluegreen-app 2>/dev/null || true
      args:
        executable: /bin/bash
      register: stop_out
      failed_when: false
    - name: Deploy (pull image, run container)
      ansible.builtin.shell: |
        set -e
        ENV=$(cat /opt/bluegreen-env 2>/dev/null || echo "{{ deploy_env }}")
        REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || echo "{{ ssm_region | default('us-east-1') }}")
        ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
        ECR_REPO=$(aws ssm get-parameter --name "/bluegreen/${ENV}/ecr_repo_name" --region "$REGION" --query Parameter.Value --output text)
        IMAGE_TAG=$(aws ssm get-parameter --name "/bluegreen/${ENV}/image_tag" --region "$REGION" --query Parameter.Value --output text)
        [[ -z "$IMAGE_TAG" || "$IMAGE_TAG" == "unset" || "$IMAGE_TAG" == "initial" ]] && { echo "ERROR: /bluegreen/${ENV}/image_tag not set"; exit 1; }
        ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
        aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
        docker pull "$ECR_URI"
        docker run -d --name bluegreen-app -p 8080:8080 -e APP_VERSION="$IMAGE_TAG" --restart unless-stopped "$ECR_URI"
      args:
        executable: /bin/bash
    - name: Wait for app
      ansible.builtin.wait_for: { port: 8080, host: 127.0.0.1, delay: 2, timeout: 30 }
    - name: Validate /health
      ansible.builtin.shell: curl -sf http://localhost:8080/health
      register: validate_out
      failed_when: validate_out.rc != 0
''', output_dir)
    return f"Deploy written to {output_dir}/deploy (CodeDeploy) and {output_dir}/ansible (Ansible). Set DEPLOY_METHOD=codedeploy or ansible."


def generate_workflows(requirements: Dict[str, Any], output_dir: str) -> str:
    """Generate GitHub Actions workflows (terraform-plan on PR, build-push on push to app/)."""
    # terraform-plan.yml: on PR to main touching infra/, assume AWS role, init+plan prod.
    _write(".github/workflows/terraform-plan.yml", '''name: Terraform Plan
on:
  pull_request:
    branches: [main]
    paths: ["infra/**"]
jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ secrets.AWS_REGION }}
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Plan
        run: |
          cd infra/envs/prod
          terraform init -backend-config=backend.hcl -reconfigure
          terraform plan -var-file=prod.tfvars
''', output_dir)
    # build-push.yml: on push to main touching app/, assume AWS role, get ECR repo from SSM, build/tag/push, update image_tag in SSM.
    _write(".github/workflows/build-push.yml", '''name: Build and Push Image
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
''', output_dir)
    return f"GitHub Actions workflows written to {output_dir}/.github/workflows/"


def write_run_order(output_dir: str, run_order_text: str) -> str:
    """Write RUN_ORDER.md with the sequence of commands to run after generation. run_order_text is appended (e.g. agent summary)."""
    content = f"""# Run order (generated by Full-Orchestrator)

Run these commands in order from the **generated project root** (`{output_dir}`).

## 1. Bootstrap (once)

```bash
cd infra/bootstrap
terraform init
terraform apply -auto-approve
```

Then copy outputs: `terraform output` → update `infra/envs/dev/backend.hcl` and `infra/envs/prod/backend.hcl` with bucket, dynamodb_table, and set cloudtrail_bucket in dev.tfvars and prod.tfvars.

## 2. Dev environment

```bash
cd infra/envs/dev
terraform init -backend-config=backend.hcl -reconfigure
terraform apply -auto-approve -var-file=dev.tfvars
```

## 3. Prod environment

```bash
cd infra/envs/prod
terraform init -backend-config=backend.hcl -reconfigure
terraform apply -auto-approve -var-file=prod.tfvars
```

## 4. OIDC (GitHub Actions)

Create IAM OIDC provider and role for your GitHub repo, then add secrets: AWS_ROLE_TO_ASSUME, AWS_REGION.

## 5. Build and deploy

**Build:** Push to main (app changes trigger build-push) or run Docker build + ECR push and update SSM image_tag.

**Deploy (choose one):**
- **CodeDeploy:** Upload deploy bundle (zip) to S3, then trigger deployment (e.g. `aws deploy create-deployment` or use trigger_codedeploy with application name, deployment group, s3_bucket, s3_key). Set `DEPLOY_METHOD=codedeploy` in CI if using this path.
- **Ansible:** From repo root, run: `ansible-playbook -i ansible/inventory/ec2_prod.aws_ec2.yml ansible/playbooks/deploy.yml -e ssm_bucket=YOUR_ARTIFACTS_BUCKET -e env=prod`. Get `ssm_bucket` from `terraform output -raw artifacts_bucket` in infra/envs/prod. Set `DEPLOY_METHOD=ansible` in CI if using this path.

---
{run_order_text}
"""
    _write("RUN_ORDER.md", content, output_dir)
    return f"RUN_ORDER.md written to {output_dir}/RUN_ORDER.md"
