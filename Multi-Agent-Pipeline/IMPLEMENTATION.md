# Multi-Agent Deploy Pipeline — Step-by-Step Implementation

This guide gives you the **exact steps**, **commands**, and **full file contents** to set up and run the Multi-Agent Deploy Pipeline (Terraform → Build → Deploy → Verify).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Folder structure](#2-folder-structure)
3. [Step 1: Create virtual environment and install dependencies](#3-step-1-create-virtual-environment-and-install-dependencies)
4. [Step 2: Configure environment](#4-step-2-configure-environment)
5. [Step 3: Run the pipeline](#5-step-3-run-the-pipeline)
6. [Step 4: Optional — allow Terraform apply](#6-step-4-optional--allow-terraform-apply)
7. [Full file contents (reference)](#7-full-file-contents-reference)

---

## 1. Prerequisites

- **Python 3.10+** — Check with: `python --version` or `python3 --version`.
- **crew-DevOps repo** — Multi-Agent-Pipeline is in **crew-DevOps** (next to CICD-With-AI). The pipeline runs Terraform and Docker in **CICD-With-AI**; default REPO_ROOT is crew-DevOps/CICD-With-AI.
- **Terraform** — Installed and on PATH if you want the infra agent to run init/plan/(apply).
- **Docker** — Installed and on PATH if you want the build agent to run docker build and push.
- **AWS credentials** — Configured so Terraform, ECR, SSM, and CodeDeploy can run.
- **OpenAI API key** — For CrewAI (set in `.env`).
- **Production URL** — Your real prod URL (e.g. from `terraform output -raw https_url` in CICD-With-AI/infra/envs/prod).

---

## 2. Folder structure

Multi-Agent-Pipeline is in **crew-DevOps** (next to CICD-With-AI and Full-Orchestrator):

```
crew-DevOps/
├── CICD-With-AI/          # Repo the pipeline runs against (Terraform, app, deploy)
├── Full-Orchestrator/
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
REPO_ROOT=C:/My-Projects/crew-DevOps/CICD-With-AI
ALLOW_TERRAFORM_APPLY=0
DEPLOY_METHOD=ansible    # or codedeploy (deploy step uses this to choose)
```

When Multi-Agent-Pipeline is in crew-DevOps, REPO_ROOT defaults to **CICD-With-AI** in this repo, so you usually don't need to set it. **DEPLOY_METHOD** tells the deploy agent whether to run Ansible (`run_ansible_deploy`, needs `ssm_bucket` from terraform output artifacts_bucket) or CodeDeploy (`trigger_codedeploy`, needs deploy bundle in S3).

### 4.2 Get your production URL

If you have already applied prod Terraform in CICD-With-AI:

```bash
cd ../CICD-With-AI/infra/envs/prod
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

1. **Infra Engineer** — Runs `terraform init` (with `backend.hcl` for dev/prod) and `terraform plan` for bootstrap, dev, prod in **CICD-With-AI**. If `ALLOW_TERRAFORM_APPLY=1`, runs `terraform apply`; otherwise reports "apply skipped."
2. **Build Engineer** — Runs `docker build` for CICD-With-AI/app/, reads `/bluegreen/prod/ecr_repo_name` from SSM, then pushes the image to ECR and updates `/bluegreen/prod/image_tag`.
3. **Deploy Engineer** — Tries to trigger CodeDeploy (if you have bundle in S3 and pass app/deployment group), or summarizes manual deploy steps and confirms image_tag.
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

---

## 7. Full file contents (reference)

See the files in this folder for the full source. Key behavior:

- **run.py** — Default REPO_ROOT: when in crew-DevOps, uses `CICD-With-AI` next to this folder; else parent dir.
- **flow.py** — Four tasks (Infra, Build, Deploy, Verify) in order with context chain.
- **agents.py** — Four agents with the tools listed in EXPLANATION.md.
- **.env.example** — PROD_URL, AWS_REGION, REPO_ROOT (optional), ALLOW_TERRAFORM_APPLY, OPENAI_API_KEY.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Create venv and `pip install -r requirements.txt` in crew-DevOps/Multi-Agent-Pipeline |
| 2 | Copy `.env.example` to `.env`; set `PROD_URL` and `OPENAI_API_KEY` |
| 3 | Run `python run.py` (or `python run.py https://your-prod-url`) |
| 4 | Optionally set `ALLOW_TERRAFORM_APPLY=1` to allow Terraform apply |

For **concepts** and **why** the pipeline works this way, see **EXPLANATION.md**.
