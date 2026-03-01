# Combined-Crew — How It Works

This document explains how the **Combined-Crew** ties together **Full-Orchestrator** and **Multi-Agent-Pipeline** in one run.

---

## What is the Combined-Crew?

The **Combined-Crew** is a single CrewAI crew that runs **five tasks in order**:

1. **Generate** — Same as Full-Orchestrator: from a `requirements.json` file, generate a full deployment project (Terraform bootstrap, platform, dev/prod envs, Node.js app, CodeDeploy bundle, GitHub Actions) into an **output directory**. Then run terraform validate and docker build, and write RUN_ORDER.md.

2. **Infra** — Same as the first step of Multi-Agent-Pipeline: run Terraform init and plan (and apply if `ALLOW_TERRAFORM_APPLY=1`) for bootstrap, dev, and prod **in the generated output directory**.

3. **Build** — Docker build for the app, push to ECR, update SSM `/bluegreen/prod/image_tag` (again, in the generated project).

4. **Deploy** — Trigger CodeDeploy or report manual deploy steps.

5. **Verify** — HTTP health check (if `PROD_URL` is set) and SSM read for image_tag and ecr_repo_name.

So you get: **from requirements to generated project to (optionally) deployed and verified** in one crew run.

---

## Why use it?

- **Single entry point** — One script and one crew for “generate + pipeline” instead of running Full-Orchestrator and then Multi-Agent-Pipeline separately.
- **Same layout as the two crews** — The same agents and tools from Full-Orchestrator and Multi-Agent-Pipeline are used; Combined-Crew only chains their tasks and sets the pipeline’s repo root to the output directory.
- **Flexible verify** — If you don’t set `PROD_URL`, the verify step only reads SSM and skips the health check (useful before you have a live URL).

---

## How does it work?

- **Location:** Combined-Crew lives in **crew-DevOps** next to **Full-Orchestrator** and **Multi-Agent-Pipeline**. It adds both sibling folders to `sys.path` and imports:
  - From **Full-Orchestrator:** `create_orchestrator_agent`, `create_orchestrator_tools` (for the generate task).
  - From **Multi-Agent-Pipeline:** `set_repo_root`, `infra_engineer`, `build_engineer`, `deploy_engineer`, `verifier_agent` (for the four pipeline tasks).

- **Output directory:** You pass `--output-dir` (or `OUTPUT_DIR`). The generate phase writes everything there. Then `set_repo_root(output_dir)` is called so all pipeline tools (Terraform, Docker, ECR, SSM, health check) run relative to that directory.

- **Requirements:** You pass a path to `requirements.json` (or use the default in Combined-Crew). It has the same shape as in Full-Orchestrator (project, region, dev/prod settings).

- **Prod URL:** Optional. If you set `PROD_URL` (or `--prod-url`), the verifier calls the health endpoint. If not, it only reads SSM and reports “health check skipped.”

- **Terraform apply:** As in Multi-Agent-Pipeline, Terraform apply runs only when `ALLOW_TERRAFORM_APPLY=1`; otherwise the infra task only runs plan.

---

## What you need

- **Python 3.10+** and the dependencies in `requirements.txt`.
- **Full-Orchestrator** and **Multi-Agent-Pipeline** as **sibling folders** in crew-DevOps (Combined-Crew imports from them).
- **requirements.json** in Combined-Crew (or path via `REQUIREMENTS_JSON` / first CLI arg).
- **OPENAI_API_KEY** in `.env` (or environment).
- **Optional:** `PROD_URL` for the verify health check; `ALLOW_TERRAFORM_APPLY=1` to allow apply; `OUTPUT_DIR` to override the output directory.

---

## Summary

| Concept | Meaning |
|--------|--------|
| **Combined-Crew** | One crew: Generate (Full-Orchestrator) + Infra + Build + Deploy + Verify (Multi-Agent-Pipeline) on the generated output. |
| **Output directory** | Where the project is generated; pipeline runs Terraform/Docker/ECR/SSM from here. |
| **Five tasks** | Generate → Infra → Build → Deploy → Verify, in order, with context chained. |
| **Sibling folders** | Must have Full-Orchestrator and Multi-Agent-Pipeline next to Combined-Crew so imports work. |

For setup and commands, see **README.md**.

---

## Gradio UI — For Absolute Beginners

### What is the Gradio UI?

Instead of running `python run.py requirements.json` from the command line, you can use a **web interface** where you fill in boxes, choose options, and click a button to run the crew.

### What can you do from the UI?

1. **Provide requirements**  
   Either upload a `requirements.json` file or paste its contents into a text box.

2. **Set run options**  
   - Where to save the generated project (output directory)  
   - Production URL (optional, for health checks)  
   - AWS region  

3. **Choose deploy method**  
   - **ansible** — Uses Ansible over SSM (no CodeDeploy)  
   - **ssh_script** — Connects via SSH to EC2 instances  
   - **ecs** — Updates an ECS service  

4. **For ssh_script: PEM key**  
   When you pick "ssh_script", you must tell the system how to find your SSH key:
   - **Upload** — Click "Upload PEM key" and select your `.pem` file  
   - **Path** — Or type the full path (e.g. `C:/keys/my-ec2-key.pem`)  

   You also need the **AWS key pair name** (the name you gave the key in AWS).

5. **Terraform apply**  
   A checkbox controls whether Terraform is allowed to apply changes. Unchecked = plan only (safer for testing).

### How do I run the UI?

```bash
cd Combined-Crew
pip install -r requirements.txt   # installs Gradio and other deps
python ui.py
```

Then open the URL shown (usually `http://127.0.0.1:7860`) in your browser.

### Do I still need .env?

Yes. The UI uses the same `.env` file as the CLI. At minimum, set `OPENAI_API_KEY`. For AWS (Terraform, ECR, deploy), configure your AWS credentials.

### Deploying on Hugging Face

You can host this UI on [Hugging Face Spaces](https://huggingface.co/spaces). See **IMPLEMENTATION.md** for step-by-step deployment instructions. Note: the crew run can take several minutes; free Spaces have time limits, so consider paid hardware or running long jobs locally.
