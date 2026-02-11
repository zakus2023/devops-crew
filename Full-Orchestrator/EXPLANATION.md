# Full-Orchestrator — Beginner-Level Explanation

This document explains **what** the Full-Orchestrator is, **why** you might use it, and **how** it works in plain language.

---

## What is the Full-Orchestrator?

The **Full-Orchestrator** is a **CrewAI crew** that takes a single **requirements file** (a JSON file describing your project) and **generates a complete deployment project** for you. It does not run Terraform or deploy anything by itself; it **creates all the files** you need so that you (or your CI) can run them in the right order.

Think of it as a **project generator**: you describe *what* you want (project name, regions, domains, instance sizes, etc.), and the crew produces:

- **Infrastructure as Code** — Terraform for bootstrap (state bucket, lock table), a platform module (VPC, load balancer, EC2, ECR, etc.), and separate dev and prod environments.
- **Application code** — A small Node.js app and a Dockerfile.
- **Deployment scripts** — CodeDeploy appspec and lifecycle scripts (install, stop, start, validate).
- **CI/CD** — GitHub Actions workflows for Terraform plan and for building/pushing the Docker image.

At the end, the crew also **validates** what it generated (e.g. `terraform validate`, `docker build`) and writes a **RUN_ORDER.md** file that tells you exactly which commands to run first, second, third, and so on.

---

## Why use it?

- **Save time** — Instead of copying a reference repo and editing dozens of files by hand, you fill in one JSON file and run the crew. The structure and wiring are already correct.
- **Fewer mistakes** — Names, regions, and parameters are derived from one place (requirements), so you get consistent values across Terraform, app, and workflows.
- **Learning** — You see a full, runnable layout (bootstrap → dev → prod → app → deploy → CI) and can study the generated files and RUN_ORDER to understand the flow.
- **Starting point** — The generated project is a known-good structure. You can then customize Terraform, app, or workflows as needed.

---

## How does it work?

### 1. You provide requirements

You write (or edit) a **requirements.json** file. It contains things like:

- **project** — e.g. `"bluegreen"` (used in resource names and SSM paths).
- **region** — e.g. `"us-east-1"`.
- **dev** and **prod** — Each has:
  - **domain_name** — e.g. `"dev-app.example.com"` or `"app.example.com"`.
  - **hosted_zone_id** — Your Route53 hosted zone ID.
  - **alarm_email** — Email for CloudWatch alarms.
  - **vpc_cidr**, **public_subnets**, **private_subnets** — Network layout.
  - **instance_type**, **min_size**, **max_size**, **desired_capacity** — EC2 and Auto Scaling.
  - **ami_id** — Optional; leave empty to use a default.

There is an example **requirements.json** in this folder. You copy it, change the values to match your AWS account and domains, and save.

### 2. You run the crew

From this folder you run:

```bash
python run.py
```

(or you pass a path to your requirements file and an output directory). The script:

- Loads **requirements.json**.
- Creates an **output directory** (e.g. `./output`).
- Starts a **CrewAI crew** with one agent (the “Full Stack DevOps Orchestrator”) and one big task.

### 3. The crew generates files

The **agent** has **tools** that do one thing each, for example:

- **generate_bootstrap** — Writes Terraform for the bootstrap (S3 bucket for state, DynamoDB table for locking, KMS key, CloudTrail bucket).
- **generate_platform** — Writes the platform Terraform module (simplified in this repo; see IMPLEMENTATION.md for the full module from the reference project).
- **generate_dev_env** — Writes the dev environment (main.tf, variables, backend.hcl, dev.tfvars).
- **generate_prod_env** — Same for prod.
- **generate_app** — Writes the Node.js app (package.json, server.js, Dockerfile).
- **generate_deploy** — Writes the CodeDeploy appspec and scripts.
- **generate_workflows** — Writes GitHub Actions YAML.
- **terraform_validate** — Runs `terraform validate` in a given directory.
- **docker_build** — Runs `docker build` in the app directory.
- **write_run_order** — Writes **RUN_ORDER.md** with the command sequence.

The **task** tells the agent: “Generate bootstrap, then platform, then dev, then prod, then app, then deploy, then workflows; then validate Terraform and Docker; then write RUN_ORDER.md and summarize.”

The agent **calls these tools in order** and uses the **requirements** that were passed when the crew was created. All file paths are relative to the **output directory**, so your current project is not overwritten.

### 4. You get a ready-to-run project

After the crew finishes:

- The **output directory** contains the full layout: `infra/bootstrap/`, `infra/modules/platform/`, `infra/envs/dev/`, `infra/envs/prod/`, `app/`, `deploy/`, `.github/workflows/`.
- **RUN_ORDER.md** explains the exact steps: first bootstrap, then fill backend and tfvars from bootstrap outputs, then dev apply, then prod apply, then OIDC and GitHub secrets, then build and deploy.

You (or your team) then follow RUN_ORDER.md. The crew does **not** run `terraform apply` or push images; it only **generates and validates** so that you keep control of when and where changes are applied.

---

## What is CrewAI and what is the “agent”?

- **CrewAI** is a framework for building **AI agents** that use **tools** (functions) to do work. You define agents (roles, goals, backstories) and tasks (descriptions, expected outputs), and the framework uses an **LLM** (e.g. OpenAI) to decide which tool to call and with what arguments.
- In this project there is **one agent**: the “Full Stack DevOps Orchestrator.” Its **goal** is to generate the full project from requirements and validate it. Its **tools** are the generation and validation functions above.
- The **flow** is **sequential**: one task that tells the agent to do all steps in order. The agent does not create infrastructure itself; it only **writes files** and **runs validate/build** in the output directory.

---

## What do I need to run it?

- **Python 3.10+** on your machine.
- **requirements.json** — You can start from the example in this folder.
- **OPENAI_API_KEY** — Set in the environment or in a `.env` file in this folder; CrewAI uses it to call the LLM.
- **Optional:** Terraform and Docker installed if you want the crew to run `terraform validate` and `docker build` successfully. If they are not installed, the crew will report that and still generate all files and RUN_ORDER.md.
- **Optional app source:** Set **APP_PATH** in `.env` (or **app_path** in requirements.json) to an existing app directory to copy instead of generating the default app. If unset, the generator uses **crew-DevOps/app** when present, else the built-in default app.

### What is in requirements.txt?

| Package | Why it's there |
|---------|----------------|
| **crewai** | Core framework: defines and runs the orchestrator agent and its tasks (read requirements, generate infra + app, write RUN_ORDER). |
| **crewai-tools** | Provides the `@tool` decorator and tool runtime so the agent can use the custom tools in `tools.py`. |
| **requests** | HTTP client for any tool that makes HTTP calls (e.g. fetch a template, health check). |
| **boto3** | AWS SDK for any tool that talks to AWS (e.g. SSM, S3) during generation or to read/write config. |
| **python-dotenv** | Loads `.env` (e.g. OPENAI_API_KEY, OUTPUT_DIR) so `run.py` can use env vars without exporting them in the shell. |

---

## Summary

| Concept | Meaning |
|--------|--------|
| **Full-Orchestrator** | A CrewAI crew that generates a full deployment project from a requirements JSON file. |
| **Requirements** | A JSON file with project name, region, and dev/prod settings (domains, VPC, instances, etc.). |
| **Output directory** | Where the crew writes all generated files (e.g. `./output`). Your repo is not modified. |
| **Agent** | One AI agent with tools to generate bootstrap, platform, envs, app, deploy, workflows and to validate. |
| **RUN_ORDER.md** | A file the crew writes in the output directory with the exact command sequence for you to run next. |

For **step-by-step setup**, full file listings, and all commands, see **IMPLEMENTATION.md**.
