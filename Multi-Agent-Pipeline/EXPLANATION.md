# Multi-Agent Deploy Pipeline — Beginner-Level Explanation

This document explains **what** the Multi-Agent Deploy Pipeline is, **why** you might use it, and **how** it works in plain language.

---

## What is the Multi-Agent Deploy Pipeline?

The **Multi-Agent Deploy Pipeline** is a **CrewAI crew** that runs a **four-step deployment flow** on a **deployment project** (a directory that contains Terraform, app, and deploy assets):

1. **Terraform** — Init, plan, and (optionally) apply for bootstrap, dev, and prod.
2. **Build** — Build the Docker image, push to ECR, and update the SSM parameter `/bluegreen/prod/image_tag`.
3. **Deploy** — Trigger deployment so the new image runs in production. Supported methods: **Ansible**, **SSH script**, or **ECS**. Option 3 (Terraform user_data/cloud-init) is for first-boot only; for ongoing updates you use one of the three methods. See **IMPLEMENTATION.md** for what you must do for each.
4. **Verify** — Check the production health URL and SSM parameters to confirm the deployment.

Unlike the **Full-Orchestrator** (which *generates* that project from requirements), this pipeline **executes** real steps: it runs Terraform, Docker, ECR push, SSM updates, and deploy. It uses **four specialist agents**, one per step, that work in sequence.

This folder lives in **crew-DevOps** (next to Full-Orchestrator and Combined-Crew). You point it at a **deployment project** via **REPO_ROOT** — for example **Full-Orchestrator/output** after you have generated a project, or any directory with the same layout (`infra/`, `app/`, `deploy/`, `ansible/`).

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
- **REPO_ROOT** — Path to your **deployment project** (the directory with `infra/bootstrap`, `infra/envs/dev`, `infra/envs/prod`, `app/`, `deploy/`, `ansible/`). Typically **Full-Orchestrator/output** after running Full-Orchestrator. If unset, the pipeline uses the parent of Multi-Agent-Pipeline (crew-DevOps) as repo root.
- **APP_ROOT** — Optional path to the app directory for Docker build. When **crew-DevOps/app** exists, run.py uses it automatically for the Build step; otherwise the app is at `REPO_ROOT/app`.
- **ALLOW_TERRAFORM_APPLY=1** — Allow the infra agent to run `terraform apply`; if unset, only **plan** runs.
- **DEPLOY_METHOD** — Set to **ansible**, **ssh_script**, or **ecs** so the deploy agent runs the chosen method. See [When to use which method](#when-to-use-which-deploy_method) below and **IMPLEMENTATION.md** (§6.3) for details.

**When to use which DEPLOY_METHOD**

- **ssh_script** — EC2 instances running your app (with or without a bastion), you have an SSH key, and you want the pipeline to SSH in and run Docker (pull image, restart container). No Ansible required.
- **ansible** — You have Ansible playbooks and dynamic inventory in the repo; you’re fine installing Ansible and `community.aws`. Good for playbook-based or multi-step deploys.
- **ecs** — Your app runs on ECS (Fargate or EC2); you want the pipeline to update the ECS service with the new image.

#### Using ssh_script deploy (beginner walkthrough)

When **DEPLOY_METHOD=ssh_script**, the Deploy step does **not** use Ansible. Instead it:

1. **Finds** your EC2 instances in AWS (by tag `Env=prod` or `Env=dev`).
2. **Connects** to each instance via SSH (directly, or through a **bastion** if instances are in private subnets).
3. **Runs a short script** on each instance: read the new image tag from SSM → log in to ECR → pull the new Docker image → stop the old app container → start the new one with `sudo docker run`.

**What you need:**

| Step | What to do |
|------|------------|
| 1 | Set `DEPLOY_METHOD=ssh_script` in `.env`. |
| 2 | Set `SSH_KEY_PATH` to the full path of your `.pem` file (the same key pair you use for EC2 in AWS). |
| 3 | Ensure your app EC2 instances are tagged **Env=prod** (or **Env=dev**). |
| 4 | If instances are in **private subnets**, enable the bastion in Terraform (`enable_bastion = true`, `key_name = "..."`) and apply; you can leave **BASTION_HOST** unset so the pipeline reads the bastion IP from Terraform. |
| 5 | Run `python run.py`. The Build step pushes the new image and updates SSM; the Deploy step SSHs to each instance and runs the script above. |

**Why it works:** The pipeline uses your SSH key to connect (optionally via a bastion). On each host it runs `sudo docker` so the `ec2-user` can access the Docker daemon. The script gets the image tag and ECR repo name from SSM (the same values the Build step just wrote), so every instance pulls and runs the same new image. For more detail and troubleshooting, see **IMPLEMENTATION.md** (§6.3, Option 2 and the step-by-step checklist).

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
| 2 | **Build Engineer** | Run `docker build` for the app (at APP_ROOT or REPO_ROOT/app), read ECR repo name from SSM, then `ecr_push_and_ssm` to push the image and update `/bluegreen/prod/image_tag`. |
| 3 | **Deployment Engineer** | Deploy via **Ansible**, **SSH script** (run_ssh_deploy), or **ECS** (run_ecs_deploy). Uses **DEPLOY_METHOD** to choose the tool. |
| 4 | **Deployment Verifier** | Call `http_health_check(PROD_URL/health)` and `read_ssm_parameter` for `/bluegreen/prod/image_tag` and `/bluegreen/prod/ecr_repo_name`. Report pass/fail. |

Each agent has **tools** (functions) it can call. The LLM decides when to call which tool and with what arguments. Task 2 can use the **context** of Task 1 (e.g. "infra is ready"), Task 3 uses context of Task 2, and Task 4 uses context of Task 3.

### 3. You get a summary

At the end you see a **pipeline result** that combines the outputs of all four tasks: Terraform status, build/push/SSM status, deploy status, and verification (health + SSM).

---

## What are the agents and tools?

- **Infra Engineer** — Tools: `terraform_init`, `terraform_plan`, `terraform_apply`. Works in `infra/bootstrap`, `infra/envs/dev`, `infra/envs/prod` under REPO_ROOT.
- **Build Engineer** — Tools: `docker_build`, `ecr_push_and_ssm`, `read_ssm_parameter`. Builds the app (APP_ROOT or REPO_ROOT/app), pushes to ECR, updates SSM.
- **Deploy Engineer** — Tools: `run_ansible_deploy`, `run_ssh_deploy`, `run_ecs_deploy`, `get_terraform_output`, `read_ssm_parameter`. Uses **DEPLOY_METHOD** (ansible | ssh_script | ecs) to run the matching deploy.
- **Verifier** — Tools: `http_health_check`, `read_ssm_parameter`. Checks the health URL and SSM parameters.

---

## What do I need?

- **Python 3.10+** and the dependencies in `requirements.txt`.
- **A deployment project** — A directory with `infra/` (bootstrap, envs/dev, envs/prod), `app/`, `deploy/`, and `ansible/`. Typically **Full-Orchestrator/output** after you run Full-Orchestrator. Set **REPO_ROOT** to that path (e.g. `REPO_ROOT=../Full-Orchestrator/output`).
- **AWS credentials** — For Terraform, ECR push, SSM, and Ansible. Configure `aws configure` or env vars.
- **PROD_URL** — Your production URL (e.g. from Terraform output `https_url`).
- **OPENAI_API_KEY** — For CrewAI.
- **Optional:** Set `ALLOW_TERRAFORM_APPLY=1` to allow Terraform apply. Set **DEPLOY_METHOD** to **ansible**, **ssh_script**, or **ecs**; see **IMPLEMENTATION.md** for what you must do for each.

---

## Summary

| Concept | Meaning |
|--------|--------|
| **Multi-Agent Pipeline** | A CrewAI crew that runs Terraform → Build → Deploy → Verify on a deployment project. |
| **Deployment project** | A directory (e.g. Full-Orchestrator/output) with infra/, app/, deploy/, ansible/. Set via **REPO_ROOT**. |
| **Location** | In **crew-DevOps**, next to Full-Orchestrator and Combined-Crew. |
| **Four agents** | Infra Engineer (Terraform), Build Engineer (Docker/ECR/SSM), Deploy Engineer (Ansible, SSH script, or ECS), Verifier (health + SSM). |
| **Sequential flow** | One task per agent; each task can use the previous task's output as context. |
| **Safety** | Terraform apply only when `ALLOW_TERRAFORM_APPLY=1`; otherwise only plan. |

For **step-by-step setup**, **full file contents**, and **commands**, see **IMPLEMENTATION.md**.
