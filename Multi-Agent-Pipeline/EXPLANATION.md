# Multi-Agent Deploy Pipeline — Beginner-Level Explanation

This document explains **what** the Multi-Agent Deploy Pipeline is, **why** you might use it, and **how** it works in plain language.

---

## What is the Multi-Agent Deploy Pipeline?

The **Multi-Agent Deploy Pipeline** is a **CrewAI crew** that runs a **four-step deployment flow** on the **existing CICD-With-AI repo**:

1. **Terraform** — Init, plan, and (optionally) apply for bootstrap, dev, and prod.
2. **Build** — Build the Docker image, push to ECR, and update the SSM parameter `/bluegreen/prod/image_tag`.
3. **Deploy** — Trigger CodeDeploy (or report manual deploy steps) so the new image runs in production.
4. **Verify** — Check the production health URL and SSM parameters to confirm the deployment.

Unlike the **Full-Orchestrator** (which *generates* files from requirements), this pipeline **executes** real steps: it runs Terraform, Docker, ECR push, SSM updates, and optionally CodeDeploy. It uses **four specialist agents**, one per step, that work in sequence.

This folder lives in **crew-DevOps** (next to CICD-With-AI and Full-Orchestrator). By default it uses **CICD-With-AI** in this repo as the repo root for Terraform and Docker.

---

## Why use it?

- **Single command** — Run one script (`python run.py`) and the crew runs Terraform → Build → Deploy → Verify in order, with the LLM deciding how to call each tool.
- **Clear roles** — Each agent has a focused job (infra, build, deploy, verify), so the flow is easy to understand and debug.
- **Safety** — Terraform **apply** runs only when you set `ALLOW_TERRAFORM_APPLY=1`; by default the infra agent only runs **plan**.
- **Verification** — The verifier agent checks the health endpoint and SSM at the end, so you get a clear pass/fail.

---

## How does it work?

### 1. You run the pipeline

From the **Multi-Agent-Pipeline** folder (in crew-DevOps) you set at least:

- **PROD_URL** — Your production base URL (e.g. `https://app.example.com`). The verifier will check `PROD_URL/health`.
- **OPENAI_API_KEY** — For CrewAI.

Optional:

- **AWS_REGION** — Default `us-east-1`.
- **REPO_ROOT** — Path to the CICD-With-AI repo; when this folder is in crew-DevOps, default is **CICD-With-AI** in this repo.
- **APP_ROOT** — Optional path to the app directory for Docker build. When **crew-DevOps/app** exists, run.py uses it automatically; Terraform still uses REPO_ROOT (CICD-With-AI).
- **ALLOW_TERRAFORM_APPLY=1** — Allow the infra agent to run `terraform apply`; if unset, only **plan** runs.

Then you run:

```bash
python run.py
```

(or `python run.py https://app.example.com`).

### 2. The crew runs four tasks in order

The crew has **four agents** and **four tasks** in **sequential** order:

| Step | Agent | Task |
|------|--------|------|
| 1 | **Infrastructure Engineer** | Run `terraform init` (with backend config for dev/prod), then `terraform plan` for bootstrap, dev, prod. If `ALLOW_TERRAFORM_APPLY=1`, run `terraform apply`. Summarize results. |
| 2 | **Build Engineer** | Run `docker build` for the app, read ECR repo name from SSM, then `ecr_push_and_ssm` to push the image and update `/bluegreen/prod/image_tag`. |
| 3 | **Deployment Engineer** | Deploy via **CodeDeploy** (trigger_codedeploy when deploy bundle is in S3) or **Ansible** (run_ansible_deploy with ssm_bucket and env). Set **DEPLOY_METHOD=codedeploy** or **DEPLOY_METHOD=ansible** to choose; agent uses it to pick the right tool. |
| 4 | **Deployment Verifier** | Call `http_health_check(PROD_URL/health)` and `read_ssm_parameter` for `/bluegreen/prod/image_tag` and `/bluegreen/prod/ecr_repo_name`. Report pass/fail. |

Each agent has **tools** (functions) it can call. The LLM decides when to call which tool and with what arguments. Task 2 can use the **context** of Task 1 (e.g. "infra is ready"), Task 3 uses context of Task 2, and Task 4 uses context of Task 3.

### 3. You get a summary

At the end you see a **pipeline result** that combines the outputs of all four tasks: Terraform status, build/push/SSM status, deploy status, and verification (health + SSM).

---

## What are the agents and tools?

- **Infra Engineer** — Tools: `terraform_init`, `terraform_plan`, `terraform_apply`. Works in `infra/bootstrap`, `infra/envs/dev`, `infra/envs/prod`.
- **Build Engineer** — Tools: `docker_build`, `ecr_push_and_ssm`, `read_ssm_parameter`. Builds the app image, pushes to ECR, updates SSM.
- **Deploy Engineer** — Tools: `trigger_codedeploy`, `run_ansible_deploy`, `read_ssm_parameter`. Uses **DEPLOY_METHOD** (codedeploy | ansible) to run CodeDeploy or Ansible deploy.
- **Verifier** — Tools: `http_health_check`, `read_ssm_parameter`. Checks the health URL and SSM parameters.

---

## What do I need?

- **Python 3.10+** and the dependencies in `requirements.txt`.
- **CICD-With-AI repo** — In crew-DevOps it sits next to this folder; `REPO_ROOT` defaults to that. The pipeline runs Terraform and Docker there.
- **AWS credentials** — For Terraform, ECR push, SSM, and CodeDeploy. Configure `aws configure` or env vars.
- **PROD_URL** — Your real production URL (e.g. from Terraform output `https_url`).
- **OPENAI_API_KEY** — For CrewAI.
- **Optional:** Set `ALLOW_TERRAFORM_APPLY=1` to allow Terraform apply. Set **DEPLOY_METHOD=codedeploy** or **DEPLOY_METHOD=ansible** so the deploy agent runs the chosen method.

---

## Summary

| Concept | Meaning |
|--------|--------|
| **Multi-Agent Pipeline** | A CrewAI crew that runs Terraform → Build → Deploy → Verify on the CICD-With-AI repo. |
| **Location** | In **crew-DevOps**, next to CICD-With-AI and Full-Orchestrator. Uses CICD-With-AI as repo root by default. |
| **Four agents** | Infra Engineer (Terraform), Build Engineer (Docker/ECR/SSM), Deploy Engineer (CodeDeploy or manual), Verifier (health + SSM). |
| **Sequential flow** | One task per agent; each task can use the previous task's output as context. |
| **Safety** | Terraform apply only when `ALLOW_TERRAFORM_APPLY=1`; otherwise only plan. |

For **step-by-step setup**, **full file contents**, and **commands**, see **IMPLEMENTATION.md**.
