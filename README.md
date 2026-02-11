# crew-DevOps

CrewAI-based DevOps: generate deployment projects and run Terraform → Build → Deploy → Verify pipelines.

## Layout

| Folder | Purpose |
|--------|--------|
| **app/** | Sample Node.js app (Express, `/health`, `/api/info`, sample webpage). Used by **Multi-Agent-Pipeline** for Docker build when present; Terraform and infra stay in **CICD-With-AI**. |
| **Full-Orchestrator/** | Generate a full project (Terraform, app, CodeDeploy, GitHub Actions) from **requirements.json**. |
| **Multi-Agent-Pipeline/** | Run Terraform → Build → Deploy → Verify on **CICD-With-AI** (or generated output). Build step uses **crew-DevOps/app** when it exists. |
| **Combined-Crew/** | Run Full-Orchestrator then the pipeline (Generate → Infra → Build → Deploy → Verify) in one crew. |
| **infra/modules/platform/** | Full Terraform platform module (VPC, ALB, ASG, ECR, SSM, CodeDeploy, etc.). **Full-Orchestrator** copies this into generated output when present. |
| **CICD-With-AI/** | Reference repo: infra (Terraform), app, deploy, Ansible, GitHub Actions. Pipeline uses it for Terraform; app can be **crew-DevOps/app** or **CICD-With-AI/app**. |

## Quick start

- **Generate a project:** `cd Full-Orchestrator && python run.py` → see **output/RUN_ORDER.md**.
- **Run the pipeline:** `cd Multi-Agent-Pipeline`, set `PROD_URL` and `OPENAI_API_KEY`, then `python run.py` (uses **CICD-With-AI** for Terraform and **app/** in this repo for Docker build when present).
- **Generate and run:** `cd Combined-Crew`, set env (e.g. `OUTPUT_DIR`, `PROD_URL`, `OPENAI_API_KEY`), then `python run.py`.

## Sample app (crew-DevOps/app)

The **app/** folder in this repo contains a small Node.js app with:

- **/health** — for ALB and verifier
- **/api/info** — hostname, version, timestamp (JSON)
- **/** — sample webpage (dark theme)

Run locally: `cd app && npm i && npm start` (port 8080). The **Multi-Agent-Pipeline** uses this app for the Build step when run from crew-DevOps (or set **APP_ROOT** to point to another app path).
