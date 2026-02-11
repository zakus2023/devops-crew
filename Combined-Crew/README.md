# Combined-Crew

**One crew that does both:** generate a full project from requirements (**Full-Orchestrator**) and then run the deploy pipeline (**Multi-Agent-Pipeline**) on the generated output.

**Flow:** Generate → Terraform → Build → Deploy → Verify (5 tasks, 5 agents in sequence).

- **Phase 1 (Generate):** Writes Terraform (bootstrap, platform, dev/prod), app, deploy bundle, and GitHub Actions to an output directory; runs terraform validate and docker build; writes RUN_ORDER.md.
- **Phase 2 (Pipeline):** Runs in the generated directory: Terraform init/plan/(apply if allowed), Docker build + ECR push + SSM update, Deploy (CodeDeploy or Ansible via **DEPLOY_METHOD**), Verify (health + SSM).

**Requires:** Full-Orchestrator and Multi-Agent-Pipeline as sibling folders in crew-DevOps (Combined-Crew imports from them).

---

## Quick start

```bash
cd Combined-Crew
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
copy .env.example .env   # set OPENAI_API_KEY; optional: PROD_URL, ALLOW_TERRAFORM_APPLY, DEPLOY_METHOD
python run.py
```

Or with options:

```bash
python run.py --output-dir ./my-output --prod-url https://app.example.com
```

See **EXPLANATION.md** for how it works and what each phase does.

---

## Step-by-step: How Combined-Crew was implemented (beginner level)

This section walks through building the Combined-Crew **in order**: create the folder, then each file one by one, with the **full file contents** so you can recreate or compare.

**Prerequisites:** You already have **Full-Orchestrator** and **Multi-Agent-Pipeline** in the same repo (e.g. `crew-DevOps/Full-Orchestrator` and `crew-DevOps/Multi-Agent-Pipeline`). Combined-Crew will sit next to them and import their agents and tools.

**Folder layout when done:**

```
crew-DevOps/
├── Full-Orchestrator/
├── Multi-Agent-Pipeline/
└── Combined-Crew/
    ├── .env.example
    ├── .gitignore
    ├── agents.py
    ├── flow.py
    ├── requirements.json
    ├── requirements.txt
    ├── run.py
    ├── tools.py
    ├── README.md
    └── EXPLANATION.md
```

---

### Step 1 — Create the folder and `requirements.txt`

Create directory `Combined-Crew` and add dependencies so we can use CrewAI and load env.

**File: `Combined-Crew/requirements.txt`**

```text
# Combined-Crew: Full-Orchestrator + Multi-Agent Pipeline
crewai>=0.80.0
crewai-tools>=0.14.0
requests>=2.28.0
boto3>=1.26.0
python-dotenv>=1.0.0
```

---

### Step 2 — Create `.env.example`

So anyone can copy it to `.env` and set the required/optional variables.

**File: `Combined-Crew/.env.example`**

```text
# Copy to .env and fill in. Do not commit .env.

# Path to requirements JSON (optional; default is requirements.json in this folder)
# REQUIREMENTS_JSON=./requirements.json

# Output directory for generated project (optional; default is ./output)
# OUTPUT_DIR=./output

# Production URL for verify step (optional; if unset, verify skips health check)
# PROD_URL=https://app.example.com

# AWS region (optional; default us-east-1)
# AWS_REGION=us-east-1

# Set to 1 to allow Terraform apply in pipeline phase (default: plan only)
# ALLOW_TERRAFORM_APPLY=1

# Deploy method: codedeploy or ansible (pipeline deploy step)
# DEPLOY_METHOD=codedeploy
# DEPLOY_METHOD=ansible

# LLM for CrewAI (required)
OPENAI_API_KEY=sk-your-openai-key-here
```

---

### Step 3 — Create `.gitignore`

**File: `Combined-Crew/.gitignore`**

```text
.venv/
.env
output/
__pycache__/
*.pyc
```

---

### Step 4 — Create `requirements.json`

Example input for the **Generate** phase (project name, region, dev/prod settings). Edit domains and IDs for your environment.

**File: `Combined-Crew/requirements.json`**

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

---

### Step 5 — Create `tools.py` (re-export from siblings)

Combined-Crew does not define its own tools; it **re-exports** from Full-Orchestrator and Multi-Agent-Pipeline. This file adds the sibling paths to `sys.path` and imports the two functions the flow needs.

**File: `Combined-Crew/tools.py`**

```python
"""
Combined-Crew tools: re-exported from Full-Orchestrator and Multi-Agent-Pipeline.

From Full-Orchestrator:
- create_orchestrator_tools(output_dir, requirements) → returns list of tools for the Generate task (generate_bootstrap, generate_platform, generate_dev_env, generate_prod_env, generate_app, generate_deploy, generate_workflows, terraform_validate, docker_build, tool_write_run_order, tool_read_file).

From Multi-Agent-Pipeline:
- set_repo_root(path) → sets the repo root for pipeline tools (Terraform, Docker, ECR, SSM, health check) so they run in the generated output_dir.
"""
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_this_dir)
_full_orch = os.path.join(_repo_root, "Full-Orchestrator")
_multi_pipe = os.path.join(_repo_root, "Multi-Agent-Pipeline")

if _full_orch not in sys.path:
    sys.path.insert(0, _full_orch)
from tools import create_orchestrator_tools

if _multi_pipe not in sys.path:
    sys.path.insert(0, _multi_pipe)
from tools import set_repo_root

__all__ = ["create_orchestrator_tools", "set_repo_root"]
```

---

### Step 6 — Create `agents.py` (re-export from siblings)

Again we only **re-export**: the orchestrator agent from Full-Orchestrator and the four pipeline agents from Multi-Agent-Pipeline. The flow will import these by name.

**File: `Combined-Crew/agents.py`**

```python
"""
Combined-Crew agents: re-exported from Full-Orchestrator and Multi-Agent-Pipeline.

- create_orchestrator_agent(tools) → from Full-Orchestrator (used for the Generate task).
- infra_engineer, build_engineer, deploy_engineer, verifier_agent → from Multi-Agent-Pipeline (used for Infra, Build, Deploy, Verify tasks).
"""
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_this_dir)
_full_orch = os.path.join(_repo_root, "Full-Orchestrator")
_multi_pipe = os.path.join(_repo_root, "Multi-Agent-Pipeline")

if _full_orch not in sys.path:
    sys.path.insert(0, _full_orch)
from agents import create_orchestrator_agent as _create_orchestrator_agent

if _multi_pipe not in sys.path:
    sys.path.insert(0, _multi_pipe)
from agents import (
    infra_engineer,
    build_engineer,
    deploy_engineer,
    verifier_agent,
)

# Re-export so flow can do: from agents import create_orchestrator_agent, infra_engineer, ...
create_orchestrator_agent = _create_orchestrator_agent

__all__ = [
    "create_orchestrator_agent",
    "infra_engineer",
    "build_engineer",
    "deploy_engineer",
    "verifier_agent",
]
```

---

### Step 7 — Create `flow.py` (crew and five tasks)

This is where the **combined crew** is defined: one orchestrator agent (with generate tools) and four pipeline agents, and **five tasks** in sequence (Generate → Infra → Build → Deploy → Verify). Pipeline tools run in `output_dir` because we call `set_repo_root(output_dir)` before defining the pipeline tasks.

**File: `Combined-Crew/flow.py`**

```python
"""
Combined-Crew flow: Generate (Full-Orchestrator) then Terraform → Build → Deploy → Verify (Multi-Agent Pipeline).
All five tasks run in sequence; pipeline operates on the generated output_dir.

Agents and tools are defined in agents.py and tools.py (they re-export from Full-Orchestrator and Multi-Agent-Pipeline).
"""
from crewai import Crew, Process, Task

from agents import (
    create_orchestrator_agent,
    infra_engineer,
    build_engineer,
    deploy_engineer,
    verifier_agent,
)
from tools import create_orchestrator_tools, set_repo_root


def create_combined_crew(output_dir: str, requirements: dict, prod_url: str = "", aws_region: str = "us-east-1") -> Crew:
    """
    Create a crew that:
    1. Generate: full project (bootstrap, platform, dev/prod, app, deploy, workflows) into output_dir.
    2. Infra: Terraform init/plan/(apply if ALLOW_TERRAFORM_APPLY=1) in output_dir.
    3. Build: Docker build, ECR push, SSM image_tag in output_dir.
    4. Deploy: CodeDeploy or Ansible (via DEPLOY_METHOD).
    5. Verify: Health check (if PROD_URL set) and SSM read.
    """
    # Phase 1: Orchestrator agent (Full-Orchestrator tools)
    gen_tools = create_orchestrator_tools(output_dir, requirements)
    orchestrator_agent = create_orchestrator_agent(gen_tools)

    task_generate = Task(
        description=f"""Generate the full deployment project into: {output_dir}.

Do in order:
1. Generate Terraform bootstrap (generate_bootstrap).
2. Generate platform module (generate_platform).
3. Generate dev environment (generate_dev_env).
4. Generate prod environment (generate_prod_env).
5. Generate app (generate_app).
6. Generate deploy bundle (generate_deploy).
7. Generate GitHub Actions workflows (generate_workflows).
8. Run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod if Terraform is available.
9. Run docker build in app if Docker is available.
10. Write RUN_ORDER.md (tool_write_run_order).

Summarize what was generated and any validation results.""",
        expected_output="Summary: all components generated, validation results, and pointer to RUN_ORDER.md.",
        agent=orchestrator_agent,
    )

    # Pipeline runs on the generated output_dir
    set_repo_root(output_dir)

    health_url = (prod_url.rstrip("/") + "/health") if prod_url else ""
    verify_instruction = (
        f'1. Call http_health_check("{health_url}"). '
        f'2. Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}"). '
        f'3. Call read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}"). '
        "Summarize: health status, image_tag, ecr_repo_name, pass/fail."
    ) if health_url else (
        f'PROD_URL was not set. Skip http_health_check. '
        f'Call read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}") and '
        f'read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}") and report the values.'
    )

    task_infra = Task(
        description=f"""Run Terraform in the generated repo at: {output_dir}.

Only apply if ALLOW_TERRAFORM_APPLY=1. Otherwise plan only.
1. infra/bootstrap: terraform_init("infra/bootstrap"), terraform_plan("infra/bootstrap"); if allowed, terraform_apply("infra/bootstrap").
2. infra/envs/dev: terraform_init("infra/envs/dev", "backend.hcl"), terraform_plan("infra/envs/dev", "dev.tfvars"); if allowed, terraform_apply("infra/envs/dev", "dev.tfvars").
3. infra/envs/prod: terraform_init("infra/envs/prod", "backend.hcl"), terraform_plan("infra/envs/prod", "prod.tfvars"); if allowed, terraform_apply("infra/envs/prod", "prod.tfvars").

Note: backend.hcl and tfvars need bootstrap outputs; if apply fails for that reason, report it and continue. Summarize results.""",
        expected_output="Summary of Terraform init/plan/(apply) for bootstrap, dev, prod.",
        agent=infra_engineer,
        context=[task_generate],
    )

    task_build = Task(
        description=f"""Build and push from the generated repo at {output_dir}.

1. docker_build(app_relative_path="app", tag=e.g. "latest" or a timestamp).
2. read_ssm_parameter("/bluegreen/prod/ecr_repo_name", region="{aws_region}") for ECR repo name (if not yet set, report and use a placeholder).
3. ecr_push_and_ssm(ecr_repo_name, image_tag, aws_region="{aws_region}").

Summarize build and push result.""",
        expected_output="Summary: Docker build, ECR push, SSM image_tag update.",
        agent=build_engineer,
        context=[task_infra],
    )

    task_deploy = Task(
        description=f"""Trigger deployment so the new image runs in prod. Use DEPLOY_METHOD (codedeploy or ansible) to choose.

If DEPLOY_METHOD=codedeploy: use trigger_codedeploy(application_name, deployment_group_name, s3_bucket, s3_key, region="{aws_region}").
If DEPLOY_METHOD=ansible: use run_ansible_deploy(env="prod", ssm_bucket=<from terraform output artifacts_bucket>, region="{aws_region}").
If unset: prefer run_ansible_deploy if ansible/ exists and ssm_bucket available; else trigger_codedeploy if bundle in S3; else report both options. Confirm image_tag via read_ssm_parameter("/bluegreen/prod/image_tag", region="{aws_region}").""",
        expected_output="Summary: deployment triggered via CodeDeploy or Ansible, or instructions for both and current image_tag.",
        agent=deploy_engineer,
        context=[task_build],
    )

    task_verify = Task(
        description=f"""Verify deployment. {verify_instruction}""",
        expected_output="Short report: health status (or skipped if no PROD_URL), SSM image_tag, SSM ecr_repo_name, pass/fail.",
        agent=verifier_agent,
        context=[task_deploy],
    )

    return Crew(
        agents=[orchestrator_agent, infra_engineer, build_engineer, deploy_engineer, verifier_agent],
        tasks=[task_generate, task_infra, task_build, task_deploy, task_verify],
        process=Process.sequential,
        verbose=True,
    )
```

---

### Step 8 — Create `run.py` (entry point)

The script loads the requirements file and env, creates the output directory, builds the crew via `create_combined_crew`, and runs `crew.kickoff()`.

**File: `Combined-Crew/run.py`**

```python
#!/usr/bin/env python3
"""
Run the Combined-Crew: Full-Orchestrator (generate from requirements) + Multi-Agent Pipeline (Terraform → Build → Deploy → Verify).

Usage:
  python run.py [--output-dir DIR] [--prod-url URL] [requirements.json]
  Or set REQUIREMENTS_JSON, OUTPUT_DIR, PROD_URL, AWS_REGION, ALLOW_TERRAFORM_APPLY in .env.

Flow: 1) Generate full project to output_dir. 2) Run Terraform (init/plan/apply). 3) Build & push to ECR, update SSM. 4) Deploy. 5) Verify (if PROD_URL set).
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)

# Allow importing from Full-Orchestrator and Multi-Agent-Pipeline
for _path in [
    _THIS_DIR,
    os.path.join(_REPO_ROOT, "Full-Orchestrator"),
    os.path.join(_REPO_ROOT, "Multi-Agent-Pipeline"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))
except ImportError:
    pass


def load_requirements(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combined-Crew: generate from requirements then run Terraform → Build → Deploy → Verify"
    )
    parser.add_argument("requirements_file", nargs="?", default=None, help="Path to requirements.json")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for generated project (default: ./output)")
    parser.add_argument("--prod-url", "-p", default=None, help="Production URL for verify step (optional)")
    args = parser.parse_args()

    requirements_path = args.requirements_file or os.environ.get("REQUIREMENTS_JSON") or os.path.join(_THIS_DIR, "requirements.json")
    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR") or os.path.join(_THIS_DIR, "output")
    prod_url = args.prod_url or os.environ.get("PROD_URL", "")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    if not os.path.isfile(requirements_path):
        print(f"Requirements file not found: {requirements_path}")
        print("Create requirements.json or pass path. See .env.example.")
        return 1

    requirements = load_requirements(requirements_path)
    os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {os.path.abspath(output_dir)}")
    print(f"AWS region: {aws_region}")
    if prod_url:
        print(f"Prod URL (verify): {prod_url}")
    else:
        print("Prod URL: not set (verify step will skip health check)")
    if os.environ.get("ALLOW_TERRAFORM_APPLY") != "1":
        print("Terraform: plan only (set ALLOW_TERRAFORM_APPLY=1 to allow apply)")
    print()
    print("Starting Combined-Crew (Generate → Infra → Build → Deploy → Verify)...")
    print()

    from flow import create_combined_crew
    crew = create_combined_crew(output_dir=output_dir, requirements=requirements, prod_url=prod_url, aws_region=aws_region)
    result = crew.kickoff()

    print()
    print("--- Combined-Crew result ---")
    print(result)
    print()
    print(f"Generated project: {os.path.abspath(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### Step 9 — Run the crew

From the **crew-DevOps** repo root (or from `Combined-Crew` with siblings available):

```bash
cd Combined-Crew
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env: set OPENAI_API_KEY=sk-...
python run.py
```

Optional: `python run.py --output-dir ./my-output --prod-url https://app.example.com` or set `PROD_URL`, `ALLOW_TERRAFORM_APPLY`, `DEPLOY_METHOD` in `.env`.

---

### Summary (chronological file order)

| Order | File               | Purpose |
|-------|--------------------|--------|
| 1     | `requirements.txt` | Python dependencies (CrewAI, requests, boto3, python-dotenv). |
| 2     | `.env.example`     | Template for `.env` (OPENAI_API_KEY, PROD_URL, DEPLOY_METHOD, etc.). |
| 3     | `.gitignore`       | Ignore .venv, .env, output/, __pycache__. |
| 4     | `requirements.json`| Input for Generate phase (project, region, dev/prod). |
| 5     | `tools.py`         | Re-export create_orchestrator_tools and set_repo_root from siblings. |
| 6     | `agents.py`        | Re-export create_orchestrator_agent and the four pipeline agents from siblings. |
| 7     | `flow.py`          | Define the combined crew and five tasks (Generate → Infra → Build → Deploy → Verify). |
| 8     | `run.py`           | Load requirements and .env, create crew, run kickoff, print result. |

For **concepts** and how the two phases fit together, see **EXPLANATION.md**.
