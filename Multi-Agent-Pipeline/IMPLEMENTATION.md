# Multi-Agent Deploy Pipeline — Step-by-Step Implementation

This guide gives you the **exact steps**, **commands**, and **full file contents** to set up and run the Multi-Agent Deploy Pipeline (Terraform → Build → Deploy → Verify).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Folder structure](#2-folder-structure)
3. [Step 1: Create virtual environment and install dependencies](#3-step-1-create-virtual-environment-and-install-dependencies)
4. [Step 2: Configure environment](#4-step-2-configure-environment)
5. [Step 3: Run the pipeline](#5-step-3-run-the-pipeline)
6. [Step 4: Optional — allow Terraform apply](#6-step-4-optional--allow-terraform-apply) — includes [Deploy options (2–4)](#63-deploy-options-2–4-ssh-script-user_data-ecs)
7. [How the core files should be created](#7-how-the-core-files-should-be-created) — agents.py, flow.py, run.py, tools.py
8. [Full file contents (reference)](#8-full-file-contents-reference)

---

## 1. Prerequisites

- **Python 3.10+** — Check with: `python --version` or `python3 --version`.
- **crew-DevOps repo** — Multi-Agent-Pipeline is in **crew-DevOps** (next to Full-Orchestrator and Combined-Crew). You need a **deployment project** (e.g. **Full-Orchestrator/output**) with `infra/`, `app/`, `deploy/`, `ansible/`. Set **REPO_ROOT** to that path.
- **Terraform** — Installed and on PATH if you want the infra agent to run init/plan/(apply).
- **Docker** — Installed and on PATH if you want the build agent to run docker build and push.
- **Ansible** — Required for the Deploy step when using **DEPLOY_METHOD=ansible** (default). Install Ansible and the `community.aws` collection so `ansible-playbook` is on PATH. See [§1.1 Install Ansible](#11-install-ansible) below.
- **AWS credentials** — Configured so Terraform, ECR, SSM, and CodeDeploy/Ansible can run.
- **OpenAI API key** — For CrewAI (set in `.env`).
- **Production URL** — Your real prod URL (e.g. from `terraform output -raw https_url` in your deployment project’s `infra/envs/prod`).

### 1.1 Install Ansible

The Deploy agent uses **Ansible** to run the deploy playbook (SSM-based, no SSH). If `ansible-playbook` is not on PATH, the deploy step fails with "ansible-playbook not found in PATH."

**Install:**

- **Windows (pip in venv or system):**  
  `pip install ansible` then `ansible-galaxy collection install community.aws`  
  Ensure the same Python/env that has `ansible-playbook` is used when you run `python run.py` (e.g. activate the venv that has Ansible).
- **macOS / Linux:**  
  `pip install ansible` and `ansible-galaxy collection install community.aws`, or use the system package manager (e.g. `apt install ansible`, then install the collection with `ansible-galaxy`).

Check: `ansible-playbook --version` and `ansible-galaxy collection list | grep community.aws`.

**Windows:** The Deploy step runs the playbook **inside WSL** by default so Linux Ansible is used (avoids `OSError: [WinError 1] Incorrect function` on Git Bash/MinGW). Install WSL and Ubuntu, install Ansible inside Ubuntu (see **ansible_wsl_setup (1).md**), and leave `ANSIBLE_USE_WSL` unset or set to `1`. To disable and run native Ansible (may fail), set `ANSIBLE_USE_WSL=0` in `.env`. When using WSL, the pipeline passes **AWS credentials** from your current environment into the WSL command so the Ansible dynamic inventory (aws_ec2) can list EC2 instances. If you see **"no hosts matched"**, check (1) AWS credentials, (2) instances running and tagged `Env=prod`/`Env=dev`, (3) region, and optionally set **ANSIBLE_WAIT_BEFORE_DEPLOY=90** after a fresh Terraform apply.

**WSL socket/buffer error (0x80072747):** If Ansible deploy fails with "buffer space" or "queue was full" or `Wsl/Service/0x80072747`, Windows had a socket issue calling WSL. **Workarounds:** (1) Set **ANSIBLE_USE_WSL=0** in `.env` and run again (native Ansible; may hit WinError 1 in some terminals). (2) Run the pipeline **from inside WSL**: open Ubuntu/WSL, `cd` to the repo and Multi-Agent-Pipeline, then `python run.py` (no Windows→WSL call). (3) Restart WSL: `wsl --shutdown`, then open WSL again. (4) Use another deploy method: **DEPLOY_METHOD=ssh_script** (with SSH key and EC2 reachable) or CodeDeploy/ECS if configured.

---

## 2. Folder structure

Multi-Agent-Pipeline is in **crew-DevOps** (next to Full-Orchestrator and Combined-Crew). Point it at a **deployment project** via **REPO_ROOT** (e.g. Full-Orchestrator/output):

```
crew-DevOps/
├── app/                    # Optional: app for Docker build (else REPO_ROOT/app)
├── Full-Orchestrator/
│   └── output/             # Typical REPO_ROOT: generated deployment project
├── Combined-Crew/
└── Multi-Agent-Pipeline/   # This pipeline
    ├── .env                # You create from .env.example (do not commit)
    ├── .env.example
    ├── requirements.txt
    ├── run.py
    ├── flow.py
    ├── agents.py
    ├── tools.py
    ├── EXPLANATION.md
    ├── IMPLEMENTATION.md
    └── README.md
```

---

## 3. Step 1: Create virtual environment and install dependencies

**From:** `crew-DevOps/Multi-Agent-Pipeline`

```bash
cd crew-DevOps/Multi-Agent-Pipeline

# Create virtual environment
python -m venv .venv

# Activate (Windows Git Bash / CMD)
source .venv/Scripts/activate

# Activate (WSL / Linux / macOS)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 4. Step 2: Configure environment

### 4.1 Create `.env` from `.env.example`

```bash
# Windows (PowerShell)
copy .env.example .env

# WSL / Linux / macOS
cp .env.example .env
```

Edit `.env` and set at least:

```text
PROD_URL=https://app.my-iifb.click
OPENAI_API_KEY=sk-your-openai-key-here
```

Optional:

```text
AWS_REGION=us-east-1
REPO_ROOT=C:/My-Projects/crew-DevOps/Full-Orchestrator/output
ALLOW_TERRAFORM_APPLY=0
DEPLOY_METHOD=ansible    # or codedeploy | ssh_script | ecs (see §6.3 Deploy options)
```

Set **REPO_ROOT** to your deployment project (e.g. **Full-Orchestrator/output** after running Full-Orchestrator). If unset, the pipeline uses the parent of Multi-Agent-Pipeline (crew-DevOps) as repo root. **DEPLOY_METHOD** chooses the deploy method: **codedeploy**, **ansible**, **ssh_script**, or **ecs**. See [§6.3 Deploy options (2–4)](#63-deploy-options-2–4-ssh-script-user_data-ecs) for what you must do for each.

### 4.2 Production URL (PROD_URL)

The Verifier step needs your production URL to run the health check. **run.py** uses both options in order:

1. **Option A:** Try to read `https_url` from `terraform output -raw https_url` in `REPO_ROOT/infra/envs/prod`. If prod Terraform has been applied and that output exists, this URL is used automatically.
2. **Option B:** If Option A is not available (no prod dir, Terraform not applied, or output missing), **run.py** uses **PROD_URL** from `.env` or from the command line: `python run.py https://app.example.com`.

So you can set **REPO_ROOT** and run the pipeline; if Terraform has the URL, it is used. Otherwise set **PROD_URL** in `.env` or pass it as an argument.

To get the URL manually (e.g. to put in `.env`), run:

```bash
cd path/to/your/deployment-project/infra/envs/prod
terraform output -raw https_url
```

Use that value (without `/health`) for `PROD_URL`.

---

## 5. Step 3: Run the pipeline

**From:** `Multi-Agent-Pipeline` (with venv activated and `.env` set)

```bash
python run.py
```

Or pass the URL on the command line:

```bash
python run.py https://app.my-iifb.click
```

**What happens:**

1. **Infra Engineer** — Runs `terraform init` (with `backend.hcl` for dev/prod) and `terraform plan` for bootstrap, dev, prod in **REPO_ROOT** (your deployment project). If `ALLOW_TERRAFORM_APPLY=1`, runs `terraform apply`; otherwise reports "apply skipped."
2. **Build Engineer** — Runs `docker build` for the app (APP_ROOT if set, e.g. crew-DevOps/app, else REPO_ROOT/app), reads `/bluegreen/prod/ecr_repo_name` from SSM, then pushes the image to ECR and updates `/bluegreen/prod/image_tag`.
3. **Deploy Engineer** — Runs deploy per **DEPLOY_METHOD**: CodeDeploy, Ansible, SSH script (run_ssh_deploy), or ECS (run_ecs_deploy).
4. **Verifier** — Calls `http_health_check(PROD_URL/health)` and reads SSM `/bluegreen/prod/image_tag` and `/bluegreen/prod/ecr_repo_name`, then reports pass/fail.

At the end you see **Pipeline result** with a summary of all four steps.

---

## 6. Step 4: Optional — allow Terraform apply

By default the infra agent only runs **plan**. To allow **apply**:

```bash
set ALLOW_TERRAFORM_APPLY=1
python run.py
```

Or add to `.env`:

```text
ALLOW_TERRAFORM_APPLY=1
```

Use only when you are ready for the crew to change infrastructure.

### 6.1 After first bootstrap apply — backend.hcl and tfvars (automatic)

The first time the pipeline runs, **infra/bootstrap** is applied and creates an S3 bucket with a **unique name** (e.g. `bluegreen-tfstate-abc123...`). The **dev** and **prod** configs need that bucket name (and DynamoDB table, and cloudtrail bucket) in their `backend.hcl` and tfvars.

**Automatic:** The Infra agent calls **update_backend_from_bootstrap()** after a successful bootstrap apply. That tool reads `tfstate_bucket`, `tflock_table`, and `cloudtrail_bucket` from `terraform output` in infra/bootstrap and writes them into:

- **infra/envs/dev/backend.hcl** and **infra/envs/prod/backend.hcl** (bucket, dynamodb_table)
- **infra/envs/dev/dev.tfvars** and **infra/envs/prod/prod.tfvars** (cloudtrail_bucket)

So you do **not** need to fill these manually when running the pipeline with `ALLOW_TERRAFORM_APPLY=1`: the agent does it before running init for dev/prod.

**Manual fallback:** If you ever need to fill them by hand (e.g. you applied bootstrap outside the pipeline), from your deployment project run:

```bash
cd path/to/your/deployment-project
BUCKET=$(cd infra/bootstrap && terraform output -raw tfstate_bucket)
TABLE=$(cd infra/bootstrap && terraform output -raw tflock_table)
CLOUDTRAIL=$(cd infra/bootstrap && terraform output -raw cloudtrail_bucket)
```

Then set `bucket` and `dynamodb_table` in **infra/envs/dev/backend.hcl** and **infra/envs/prod/backend.hcl**, and `cloudtrail_bucket` in **infra/envs/dev/dev.tfvars** and **infra/envs/prod/prod.tfvars**.

### 6.2 Docker must be running for the Build step

If the Build step fails with "Cannot connect to the Docker daemon" or "dockerDesktopLinuxEngine: The system cannot find the file specified", **Docker is not running**. Start **Docker Desktop** (or your Docker service) on your machine, then run the pipeline again.

### 6.3 Deploy options (2–4): SSH script, user_data, ECS

The pipeline supports **four deploy methods**. Set **DEPLOY_METHOD** in `.env` and follow the steps below for the method you use.

| DEPLOY_METHOD | Tool / behavior | What you must do |
|---------------|-----------------|------------------|
| **codedeploy** | `trigger_codedeploy` | Have a deploy bundle in S3; Terraform outputs `codedeploy_app`, `codedeploy_group`. |
| **ansible** | `run_ansible_deploy` | Install Ansible + `community.aws`; Terraform output `artifacts_bucket`; ansible/ with inventory and playbooks. |
| **ssh_script** | `run_ssh_deploy` | See [Option 2: SSH + script](#option-2-ssh--script-no-ansible) and [Step-by-step (beginner)](#ssh_script-step-by-step-beginner) below. |
| **ecs** | `run_ecs_deploy` | See [Option 4: ECS](#option-4-ecs-fargate-or-ec2) below. |

#### When to use which DEPLOY_METHOD

| Method | Use when … |
|--------|------------|
| **ssh_script** | You have **EC2 instances** (in public or private subnets) running your app, you have an **SSH key** that can reach them (or a bastion), and you want the pipeline to **SSH in and run Docker** (pull new image, stop/start container). No Ansible or CodeDeploy setup needed. Good for: simple EC2 + Docker setups, private subnets with a bastion, or when you prefer “SSH + script” over Ansible. |
| **ansible** | Your deployment project has an **Ansible playbook** (e.g. `ansible/playbooks/deploy.yml`) and **dynamic inventory** (e.g. `aws_ec2`). You’re okay installing Ansible and the `community.aws` collection. Use when: you already use Ansible for config/deploy, or you want playbook-based deploys (roles, templates, many hosts) and have the `artifacts_bucket` (or similar) from Terraform. |
| **codedeploy** | Your app is deployed with **AWS CodeDeploy** (e.g. blue/green or in-place). You have a **deploy bundle** (e.g. zip in S3) and Terraform outputs for `codedeploy_app` and `codedeploy_group`. Use when: you rely on CodeDeploy for rollbacks, traffic shifting, or lifecycle hooks, and your build produces an S3 revision for CodeDeploy. |
| **ecs** | Your app runs on **Amazon ECS** (Fargate or EC2 launch type). Terraform exposes **ecs_cluster_name** and **ecs_service_name**. Use when: you’re on ECS and want the pipeline to update the service with the new image (new task definition + force new deployment). |

**Quick decision:** EC2 + Docker and you have SSH (or bastion) → **ssh_script**. Ansible playbooks already in the repo → **ansible**. CodeDeploy in your Terraform → **codedeploy**. ECS cluster + service → **ecs**.

---

#### ssh_script step-by-step (beginner)

Use this checklist when you want the pipeline to deploy via **SSH** (no Ansible, no CodeDeploy). The deploy agent will SSH into each EC2 instance tagged `Env=prod` (or `Env=dev`), run ECR login, pull the new image, and start the app container.

**Step 0 — Required for any run**  
Set **PROD_URL** and **OPENAI_API_KEY** in `.env` (see [§4 Step 2: Configure environment](#4-step-2-configure-environment)). The pipeline needs these before it runs.

**Step 1 — Choose deploy method**  
In `.env` set:
```text
DEPLOY_METHOD=ssh_script
```

**Step 2 — Provide an SSH key**  
The pipeline needs a private key that matches the key pair used by your EC2 instances (and bastion, if used).

- **Option A (recommended):** Set **SSH_KEY_PATH** to the full path to your `.pem` file, e.g.  
  `SSH_KEY_PATH=C:/My-Projects/crew-DevOps/my-key.pem`
- **Option B:** Set **SSH_PRIVATE_KEY** to the **contents** of the `.pem` file (useful if the path causes issues on Windows). The pipeline will write a temporary key file and use it for SSH.

**Step 3 — Ensure instances are tagged**  
Your app EC2 instances must have the tag **Env=prod** (or **Env=dev**). The pipeline finds instances by this tag. The bastion host is excluded (instances whose name contains "bastion" are skipped).

**Step 4 — Reachability**

- **Public subnets:** Your machine must be able to SSH to the instance IPs on port 22. Security groups must allow SSH (port 22) from your IP (or VPN).
- **Private subnets:** Use the optional **bastion**. Continue to Step 5.

**Step 5 — Bastion (only if instances are in private subnets)**  
If your app instances have private IPs only (e.g. 10.x.x.x) and are not reachable from your laptop:

1. In Terraform (e.g. **infra/envs/prod/prod.tfvars**), set:
   - `enable_bastion = true`
   - `key_name = "YOUR_AWS_KEY_PAIR_NAME"` (must match the key you use in SSH_KEY_PATH)
   - Optionally `allowed_bastion_cidr = "YOUR_IP/32"` so only your IP can SSH to the bastion
2. Run `terraform apply` (or run the pipeline with `ALLOW_TERRAFORM_APPLY=1`) so the bastion is created.
3. In `.env` you can **leave BASTION_HOST unset** — the pipeline will read `bastion_public_ip` from Terraform output automatically. Or set `BASTION_HOST=1.2.3.4` if you want to override.

The pipeline will connect: **your machine → bastion (public IP) → app instance (private IP)** using SSH ProxyCommand with your key.

**Step 6 — Run the pipeline**  
From `Multi-Agent-Pipeline` (venv activated, `.env` set):
```bash
python run.py
```
The Deploy step will call `run_ssh_deploy(env="prod", region="us-east-1")`. On each instance it runs: ECR login → `sudo docker pull` → `sudo docker stop/rm` → `sudo docker run` for the app container. If you see **"permission denied"** on the Docker socket, the script already uses `sudo` for Docker; if you still get errors, ensure the AMI has Docker installed and `ec2-user` has passwordless sudo.

**Step 7 — Troubleshooting**

| Symptom | What to check |
|--------|----------------|
| Permission denied (publickey) on bastion | Your `.pem` must match the AWS key pair name used by the bastion. Test: `ssh -i /path/to/key.pem ec2-user@BASTION_IP "echo OK"`. |
| Permission denied on Docker socket | The remote script uses `sudo docker`; ensure `ec2-user` has sudo and Docker is installed on the instance. |
| Connection timed out to 10.x.x.x | Use a bastion (Step 5); or ensure a VPN/peering allows SSH from your machine. |
| No instances found | Instances must be running and tagged `Env=prod` (or `Env=dev`) in the correct region. |

---

**Option 2: SSH + script (no Ansible)**  
When **DEPLOY_METHOD=ssh_script**, the deploy agent discovers EC2 instances by tag (`Env=prod` or `Env=dev`) in the given region, SSHs to each instance, and runs a script that reads `image_tag` and `ecr_repo_name` from SSM, runs `sudo docker pull`, then stops/removes the existing `bluegreen-app` container and runs the new one.

**What you should do (summary):**

1. **SSH key** — Set **SSH_KEY_PATH** (absolute path to your `.pem` file) or **SSH_PRIVATE_KEY** (raw key content) in `.env`. The same key is used for the bastion and for app instances when using ProxyJump.
2. **Reachability** — Your machine must reach EC2 on port 22. If instances are in **private subnets**, use the **optional bastion** (Step 5 above). Security groups must allow SSH from the runner or from the bastion security group.
3. **Tags** — Tag EC2 instances with **Env=prod** (or **Env=dev**). The bastion host is excluded from the deploy list.
4. **Optional** — Set **SSH_USER** in `.env` if your AMI uses a different user (default is `ec2-user`).
5. **Bastion (private subnets)** — In **infra/envs/prod/prod.tfvars** set `enable_bastion = true`, `key_name = "YOUR_AWS_KEY_PAIR_NAME"`. Run `terraform apply`. Leave **BASTION_HOST** unset in `.env` to auto-fetch the bastion IP from Terraform, or set it to override.

**Troubleshooting ssh_script:** If you see "Permission denied (publickey)" on the bastion, ensure **SSH_KEY_PATH** points to the correct `.pem` (same key as the bastion’s key pair). Test from your shell: `ssh -i /path/to/key.pem ec2-user@BASTION_IP "echo OK"`.

**Option 3: Terraform user_data / cloud-init (bootstrap only)**  
This is **documentation-only**: there is no separate pipeline tool. You can use Terraform to set **user_data** on EC2 (or in a launch template) so that on **first boot** the instance installs Docker, pulls the image from ECR, and runs the container (e.g. via a cloud-init script). That gives you a working app after the first apply.

For **subsequent updates** (new image tags), user_data does not re-run. You must use one of the other deploy methods for ongoing deployments: **Ansible** (`run_ansible_deploy`), **SSH script** (`run_ssh_deploy`), **CodeDeploy** (`trigger_codedeploy`), or **ECS** (`run_ecs_deploy`). So: use user_data for initial bootstrap; set **DEPLOY_METHOD** to ansible, ssh_script, codedeploy, or ecs for the pipeline’s Deploy step.

**What you should do:**

1. In your Terraform (e.g. EC2 instance or launch template), set `user_data` (or `user_data_base64`) to a script that: installs Docker if needed, logs in to ECR, pulls the image (e.g. using a fixed tag or SSM at boot), and runs `docker run` for your app.
2. For pipeline-driven updates, set **DEPLOY_METHOD** to **ansible**, **ssh_script**, **codedeploy**, or **ecs** and follow the corresponding steps in this doc.

**Option 4: ECS (Fargate)**  
When **DEPLOY_METHOD=ecs**, the deploy agent updates the ECS service to use the new image: it reads `/bluegreen/prod/image_tag` and `/bluegreen/prod/ecr_repo_name` from SSM, registers a new task definition revision with that image, and calls **update_service** with **forceNewDeployment=True**.

**What you should do:**

1. **Terraform** — Enable optional ECS in the platform module: in **infra/envs/prod/prod.tfvars** set **enable_ecs = true**. The platform module then creates an ECS cluster, Fargate service, task definition, and an ALB listener rule that forwards HTTPS traffic to the ECS target group. Terraform outputs **ecs_cluster_name** and **ecs_service_name** (and writes them to SSM at `/bluegreen/prod/ecs_cluster_name` and `/bluegreen/prod/ecs_service_name` for pipeline fallback). Run **terraform apply** so the ECS stack exists.
2. **Pipeline** — Set **DEPLOY_METHOD=ecs** in `.env`. The deploy agent gets cluster and service from **get_terraform_output**; if those outputs are missing (e.g. state not yet applied), it falls back to **read_ssm_parameter** for the two SSM names above, then calls **run_ecs_deploy**.
3. **First deploy** — After enabling ECS, run the pipeline once (Build pushes an image and updates `/bluegreen/prod/image_tag`; Deploy updates the ECS service with that image). The initial task definition uses image tag `unset` until the first pipeline run.

### 6.4 Prod Terraform apply: GuardDuty, Security Hub, Config limits

**Full-Orchestrator** now generates **dev.tfvars** and **prod.tfvars** with `enable_guardduty = false`, `enable_securityhub = false`, and `enable_config = false` by default, so new deployment projects avoid account-level conflicts (one GuardDuty detector, Security Hub subscription, or Config recorder limit per account).

If you use an older generated project or override these to `true` and then see errors like "existing AWS GuardDuty detector", "existing Security Hub subscription", or "max number of AWS Config configuration recorders exceeded":

- Set `enable_guardduty = false`, `enable_securityhub = false`, and `enable_config = false` in **infra/envs/prod/prod.tfvars** (and infra/envs/dev/dev.tfvars if needed), then re-run the pipeline or `terraform apply`.
- Or fix the account state (remove/consolidate existing resources) or use a different account/region.

---

## 7. How the core files should be created

This section describes **what each file does** and **how it should be structured** so you can recreate or adapt the pipeline.

### 7.1 `tools.py`

**Purpose:** Provides all tools the agents call: Terraform, Docker, ECR, SSM, CodeDeploy, Ansible, SSH deploy, ECS deploy, and health check. Paths are relative to **repo_root** (the deployment project, e.g. Full-Orchestrator/output).

**How to create it:**

1. **Imports** — `os`, `subprocess`, `typing.Optional`, `requests`. Use CrewAI’s `@tool` decorator (from `crewai.tools`), with a fallback if not installed (e.g. for tests).
2. **Repo and app root** — Two module-level variables: `_REPO_ROOT` and `_APP_ROOT`. Four helpers: `set_repo_root(path)`, `set_app_root(path)`, `get_repo_root()` (return set path or parent of Multi-Agent-Pipeline), `get_app_root()` (return set path or None).
3. **Terraform tools** — `terraform_init(relative_path, backend_config=None)`, `terraform_plan(relative_path, var_file=None)`, `terraform_apply(relative_path, var_file=None)`. Each: resolve `work_dir = os.path.join(get_repo_root(), relative_path)`, check directory exists, run `subprocess.run` in `work_dir`, return OK/FAIL string. For apply, only run if `ALLOW_TERRAFORM_APPLY=1`. `update_backend_from_bootstrap()` (no input): run `terraform output -raw` in infra/bootstrap for tfstate_bucket, tflock_table, cloudtrail_bucket; update infra/envs/dev and infra/envs/prod backend.hcl and tfvars with those values so dev/prod init works after the first bootstrap apply.
4. **Build tools** — `docker_build(app_relative_path="app", tag="latest")` (build in `get_app_root()` or `repo_root/app`); `ecr_push_and_ssm(ecr_repo_name, image_tag, aws_region=None)` (tag image, ECR login, push, put `/bluegreen/prod/image_tag` in SSM).
5. **Shared** — `read_ssm_parameter(name, region=None)` (boto3 SSM `get_parameter`).
6. **Deploy tools** — `run_ansible_deploy(env, ssm_bucket, ansible_dir="ansible", region=None)` (run ansible-playbook in repo’s ansible dir); `trigger_codedeploy(application_name, deployment_group_name, s3_bucket, s3_key, region=None)` (boto3 `create_deployment` with S3 revision); `run_ssh_deploy(env, region=None)` (EC2 by tag, SSH + script); `run_ecs_deploy(cluster_name, service_name, region=None)` (new task def from SSM, update service).
7. **Verify** — `http_health_check(url, timeout_seconds=10)` (requests.get, report OK if status 200–299).

Decorate every tool function with `@tool("short description for the LLM")` and give each a clear docstring. All paths used by tools come from `get_repo_root()` / `get_app_root()` so flow can set them before the crew runs.

### 7.2 `agents.py`

**Purpose:** Defines the four CrewAI agents and assigns each its tools.

**How to create it:**

1. **Imports** — `from crewai import Agent` and import all tools from `tools` (including run_ssh_deploy, run_ecs_deploy, get_terraform_output).
2. **Infra Engineer** — Role "Infrastructure Engineer"; goal to run Terraform init/plan/(apply if allowed) for bootstrap, dev, prod; tools = [terraform_init, terraform_plan, terraform_apply, update_backend_from_bootstrap]; verbose=True, allow_delegation=False.
3. **Build Engineer** — Role "Build Engineer"; goal to build Docker image, push to ECR, update SSM image_tag; tools = [docker_build, ecr_push_and_ssm, read_ssm_parameter].
4. **Deploy Engineer** — Role "Deployment Engineer"; goal to trigger deployment per DEPLOY_METHOD (codedeploy, ansible, ssh_script, or ecs); tools = [get_terraform_output, trigger_codedeploy, run_ansible_deploy, run_ssh_deploy, run_ecs_deploy, read_ssm_parameter].
5. **Verifier** — Role "Deployment Verifier"; goal to verify health endpoint and SSM params; tools = [http_health_check, read_ssm_parameter].

Backstories should tell each agent when to use which tool (e.g. apply only if ALLOW_TERRAFORM_APPLY=1; choose codedeploy vs ansible from DEPLOY_METHOD).

### 7.3 `flow.py`

**Purpose:** Builds the Crew with four sequential tasks and passes repo_root, prod_url, and app_root into the tools.

**How to create it:**

1. **Imports** — `from crewai import Crew, Process, Task` and the four agents from `agents`.
2. **Single function** — `create_pipeline_crew(repo_root, prod_url, aws_region, app_root=None)`. First call `set_repo_root(repo_root)` and `set_app_root(app_root)` (import from tools) so every tool uses the correct paths.
3. **Health URL** — `health_url = prod_url.rstrip("/") + "/health"` (used in the verify task).
4. **Four tasks** —  
   - **task_infra** — Description: run Terraform for bootstrap, then dev (with backend.hcl, dev.tfvars), then prod (with backend.hcl, prod.tfvars); apply only if ALLOW_TERRAFORM_APPLY=1. Agent = infra_engineer. Expected output: summary of init/plan/(apply) per env.
   - **task_build** — Description: docker_build, read_ssm_parameter for ECR repo name, ecr_push_and_ssm. Agent = build_engineer, context=[task_infra].
   - **task_deploy** — Description: choose deploy method from DEPLOY_METHOD (codedeploy, ansible, ssh_script, ecs); call the matching tool with correct args (e.g. ssm_bucket from terraform output for Ansible; cluster/service for ECS). Agent = deploy_engineer, context=[task_build].
   - **task_verify** — Description: http_health_check(health_url), read SSM image_tag and ecr_repo_name. Agent = verifier_agent, context=[task_deploy].
5. **Return** — `Crew(agents=[all four], tasks=[all four], process=Process.sequential, verbose=True)`.

Task descriptions should be concrete (e.g. exact tool names and typical arguments) so the LLM has clear instructions.

### 7.4 `run.py`

**Purpose:** Entry point: load env, resolve REPO_ROOT and APP_ROOT, create the crew, kick off, print result.

**How to create it:**

1. **Shebang and docstring** — Usage: set PROD_URL (and optionally AWS_REGION, REPO_ROOT, ALLOW_TERRAFORM_APPLY), then `python run.py` or `python run.py https://app.example.com`. REPO_ROOT = path to deployment project (e.g. Full-Orchestrator/output); default = parent of Multi-Agent-Pipeline (crew-DevOps) if unset.
2. **Path and env** — `_THIS_DIR = dirname(abspath(__file__))`, add to sys.path. Load `.env` from this dir (e.g. with `dotenv.load_dotenv`) if available.
3. **main()** —  
   - prod_url = env PROD_URL or sys.argv[1]; if missing, print usage and return 1.  
   - aws_region = env AWS_REGION or "us-east-1".  
   - repo_root = env REPO_ROOT or parent of Multi-Agent-Pipeline (no fallback to another repo name).  
   - If repo_root is not a directory, print error and return 1.  
   - app_root = env APP_ROOT or, if crew-DevOps/app exists, that path; else None.  
   - Print repo_root, prod_url, aws_region, app_root (if set), and a note if Terraform apply is disabled.  
   - Import `create_pipeline_crew` from flow, create crew with repo_root, prod_url, aws_region, app_root, then `crew.kickoff()`.  
   - Print "Pipeline result" and the result; return 0.
4. **Entry** — `if __name__ == "__main__": sys.exit(main())`.

REPO_ROOT must point at the **deployment project** (e.g. Full-Orchestrator/output) that contains infra/, app/, ansible/, etc. The pipeline does not depend on any other repo (e.g. CICD-With-AI); only REPO_ROOT and optional APP_ROOT.

---

## 8. Full file contents (reference)

See the files in this folder for the full source. Key behavior:

- **run.py** — Reads PROD_URL (env or CLI), REPO_ROOT (optional; default is parent of Multi-Agent-Pipeline). Set REPO_ROOT to your deployment project (e.g. Full-Orchestrator/output).
- **flow.py** — Four tasks (Infra, Build, Deploy, Verify) in order with context chain; calls set_repo_root and set_app_root.
- **agents.py** — Four agents with the tools listed in EXPLANATION.md.
- **.env.example** — PROD_URL, AWS_REGION, REPO_ROOT (optional), APP_ROOT (optional), ALLOW_TERRAFORM_APPLY, DEPLOY_METHOD, OPENAI_API_KEY.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Create venv and `pip install -r requirements.txt` in crew-DevOps/Multi-Agent-Pipeline |
| 2 | Copy `.env.example` to `.env`; set `PROD_URL` and `OPENAI_API_KEY` |
| 3 | Run `python run.py` (or `python run.py https://your-prod-url`) |
| 4 | Optionally set `ALLOW_TERRAFORM_APPLY=1` to allow Terraform apply |

For **concepts** and **why** the pipeline works this way, see **EXPLANATION.md**.
