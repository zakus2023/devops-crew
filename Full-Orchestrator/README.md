# Full-Orchestrator

Generate a **full deployment project** (Terraform, Node.js app, CodeDeploy, GitHub Actions) from a single **requirements.json** file using CrewAI.

- **EXPLANATION.md** — Beginner-level: what it is, why use it, how it works.
- **IMPLEMENTATION.md** — Step-by-step: setup, commands, and more file details.

## Quick start

```bash
cd Full-Orchestrator
python -m venv .venv
source .venv/Scripts/activate   # Bash
pip install -r requirements.txt
# Only if you don't have .env yet: copy .env.example .env, then set OPENAI_API_KEY
python run.py
```

Then follow **RUN_ORDER.md** in the `output/` directory.

---

## Step-by-step: How Full-Orchestrator was implemented (beginner level)

This section walks through building the Full-Orchestrator **in order**: create the folder, then each file with **full file contents** so you can recreate or compare.

**Prerequisites:** Python 3.10+, and (optional) Terraform and Docker for the validate steps.

**Folder layout when done:**

```
Full-Orchestrator/
├── .env.example
├── .gitignore
├── agents.py
├── flow.py
├── generators.py
├── requirements.json
├── requirements.txt
├── run.py
├── tools.py
├── README.md
├── EXPLANATION.md
└── IMPLEMENTATION.md
```

---

### Step 1 — Create the folder and `requirements.txt`

**File: `Full-Orchestrator/requirements.txt`**

```text
# Full-Orchestrator: generate infra + app from requirements
crewai>=0.80.0
crewai-tools>=0.14.0
requests>=2.28.0
boto3>=1.26.0
python-dotenv>=1.0.0
```

**What each dependency does:**

| Package | Why it's there |
|---------|----------------|
| **crewai** | Core framework: defines and runs the orchestrator agent and its tasks (read requirements, generate infra + app, write RUN_ORDER). |
| **crewai-tools** | Provides the `@tool` decorator and tool runtime so the agent can use custom tools (e.g. in `tools.py`). |
| **requests** | HTTP client for any tool that makes HTTP calls (e.g. fetch a template, health check). |
| **boto3** | AWS SDK for any tool that talks to AWS (e.g. SSM, S3) during generation or to read/write config. |
| **python-dotenv** | Loads `.env` (e.g. OPENAI_API_KEY, OUTPUT_DIR) so `run.py` can use env vars without exporting them in the shell. |

---

### Step 2 — Create `.env.example`

**File: `Full-Orchestrator/.env.example`**

```text
# Copy to .env and fill in. Do not commit .env.

# Path to requirements JSON (optional; default is requirements.json in this folder)
# REQUIREMENTS_JSON=./requirements.json

# Output directory for generated project (optional; default is ./output)
# OUTPUT_DIR=./output

# App source directory (optional). If set, app is copied from here instead of generating default.
# If unset, uses requirements "app_path", or crew-DevOps/app if present, else generated app.
# APP_PATH=C:/My-Projects/crew-DevOps/app

# LLM for CrewAI (required for the crew to run)
OPENAI_API_KEY=sk-your-openai-key-here

# If using another provider, set the appropriate env (see CrewAI docs).
# OPENAI_API_KEY=...
```

---

### Step 3 — Create `.gitignore`

**File: `Full-Orchestrator/.gitignore`**

```text
# Full-Orchestrator
.venv/
.env
output/
__pycache__/
*.pyc
.pytest_cache/
```

---

### Step 4 — Create `requirements.json`

Example input for the orchestrator (project name, region, dev/prod settings). Edit for your environment. **`ami_id` is optional** — leave empty (`""`) to use a default AMI. **`app_path` is optional** — absolute path to an app directory to copy instead of generating the default app (overridden by APP_PATH in .env).

**File: `Full-Orchestrator/requirements.json`**

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

### Step 5 — Create `generators.py`

This module writes all generated files under `output_dir`. It uses helpers `_ensure_dir`, `_write`, `_get` and implements: `generate_bootstrap`, `generate_platform`, `generate_dev_env`, `generate_prod_env`, `generate_app`, `generate_deploy`, `generate_workflows`, `write_run_order`. Each function takes `requirements` (dict) and `output_dir` (str) and writes the corresponding Terraform, app, deploy, or workflow files.

**File: `Full-Orchestrator/generators.py`** (structure; full source is in the repo)

- **Imports:** `os`, `json`, `typing.Any`, `Dict`
- **Helpers:** `_ensure_dir(file_path)`, `_write(path, content, output_dir)`, `_get(req, *keys, default)`
- **Generators:**  
  `generate_bootstrap(req, output_dir)` → infra/bootstrap (variables.tf, main.tf, outputs.tf)  
  `generate_platform(req, output_dir)` → infra/modules/platform (variables.tf, main.tf, outputs.tf; simplified)  
  `generate_dev_env(req, output_dir)` → infra/envs/dev (main.tf, variables.tf, outputs.tf, backend.hcl, dev.tfvars)  
  `generate_prod_env(req, output_dir)` → infra/envs/prod (same structure)  
  `generate_app(req, output_dir)` → app/ (package.json, server.js, Dockerfile)  
  `generate_deploy(req, output_dir)` → deploy/ (appspec.yml, scripts/install.sh, stop.sh, start.sh, validate.sh)  
  `generate_workflows(req, output_dir)` → .github/workflows/ (terraform-plan.yml, build-push.yml)  
  `write_run_order(output_dir, run_order_text)` → RUN_ORDER.md with bootstrap → dev → prod → OIDC → build/deploy (CodeDeploy or Ansible)

For the **complete** `generators.py` (all template strings and logic), see the file in the repo; it is about 620 lines.

---

### Step 6 — Create `tools.py`

Tools wrap the generators and add `terraform validate`, `docker build`, and `read_file`. They are created by `create_orchestrator_tools(output_dir, requirements)` and close over that `output_dir` and `requirements`.

**File: `Full-Orchestrator/tools.py`**

```python
"""
CrewAI tools for the Full-Orchestrator: generate infra/app from requirements and validate.
Use create_orchestrator_tools(output_dir, requirements) to get tools bound to your run.
"""
import os
import subprocess
import json
from typing import Any, Dict, List, Optional

try:
    from crewai.tools import tool
except ImportError:
    def tool(desc):
        def deco(fn):
            fn.description = desc
            return fn
        return deco

from generators import (
    generate_bootstrap,
    generate_platform,
    generate_dev_env,
    generate_prod_env,
    generate_app,
    generate_deploy,
    generate_workflows,
    write_run_order,
)


def create_orchestrator_tools(output_dir: str, requirements: Dict[str, Any]) -> List[Any]:
    """
    Create tools that are bound to the given output_dir and requirements.
    Pass these to the orchestrator agent.
    """
    out = output_dir
    req = requirements

    @tool("Generate Terraform bootstrap (S3 state bucket, DynamoDB lock, KMS). No input. Writes to the configured output directory.")
    def tool_generate_bootstrap() -> str:
        return generate_bootstrap(req, out)

    @tool("Generate platform Terraform module (VPC, ALB, ASG, ECR, SSM). No input. Writes to output directory.")
    def tool_generate_platform() -> str:
        return generate_platform(req, out)

    @tool("Generate dev environment Terraform (main.tf, variables, backend.hcl, dev.tfvars). No input.")
    def tool_generate_dev_env() -> str:
        return generate_dev_env(req, out)

    @tool("Generate prod environment Terraform (main.tf, variables, backend.hcl, prod.tfvars). No input.")
    def tool_generate_prod_env() -> str:
        return generate_prod_env(req, out)

    @tool("Generate sample Node.js app and Dockerfile (package.json, server.js, Dockerfile). No input.")
    def tool_generate_app() -> str:
        return generate_app(req, out)

    @tool("Generate CodeDeploy bundle (appspec.yml, install.sh, stop.sh, start.sh, validate.sh). No input.")
    def tool_generate_deploy() -> str:
        return generate_deploy(req, out)

    @tool("Generate GitHub Actions workflows (terraform-plan, build-push). No input.")
    def tool_generate_workflows() -> str:
        return generate_workflows(req, out)

    @tool("Run 'terraform validate' in a Terraform directory. Input: path relative to output dir, e.g. 'infra/bootstrap' or 'infra/envs/dev'. Returns validation result.")
    def tool_terraform_validate(relative_path: str) -> str:
        work_dir = os.path.join(out, relative_path)
        if not os.path.isdir(work_dir):
            return f"Error: directory not found: {work_dir}"
        try:
            result = subprocess.run(
                ["terraform", "validate"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return f"terraform validate in {relative_path}: OK"
            return f"terraform validate in {relative_path}: FAIL\nstdout: {result.stdout}\nstderr: {result.stderr}"
        except FileNotFoundError:
            return "Error: terraform not found in PATH. Install Terraform to validate."
        except subprocess.TimeoutExpired:
            return f"Error: terraform validate timed out in {relative_path}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {str(e)}"

    @tool("Run 'docker build' in an app directory to validate Dockerfile. Input: path relative to output dir, e.g. 'app'. Returns build result.")
    def tool_docker_build(relative_path: str) -> str:
        work_dir = os.path.join(out, relative_path)
        if not os.path.isdir(work_dir):
            return f"Error: directory not found: {work_dir}"
        try:
            result = subprocess.run(
                ["docker", "build", "-t", "orchestrator-test:latest", "."],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                return f"docker build in {relative_path}: OK"
            return f"docker build in {relative_path}: FAIL\nstdout: {result.stdout}\nstderr: {result.stderr}"
        except FileNotFoundError:
            return "Error: docker not found in PATH. Docker build skipped."
        except subprocess.TimeoutExpired:
            return f"Error: docker build timed out in {relative_path}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {str(e)}"

    @tool("Write RUN_ORDER.md with the command sequence. Input: optional extra text to append to the run order.")
    def tool_write_run_order(extra_text: Optional[str] = None) -> str:
        return write_run_order(out, extra_text or "")

    @tool("Read a file from the output directory. Input: path relative to output dir, e.g. 'infra/bootstrap/main.tf'. Returns file contents or error.")
    def tool_read_file(relative_path: str) -> str:
        path = os.path.join(out, relative_path)
        if not os.path.isfile(path):
            return f"Error: file not found: {path}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading {relative_path}: {type(e).__name__}: {str(e)}"

    return [
        tool_generate_bootstrap,
        tool_generate_platform,
        tool_generate_dev_env,
        tool_generate_prod_env,
        tool_generate_app,
        tool_generate_deploy,
        tool_generate_workflows,
        tool_terraform_validate,
        tool_docker_build,
        tool_write_run_order,
        tool_read_file,
    ]
```

---

### Step 7 — Create `agents.py`

Single agent: **Full Stack DevOps Orchestrator**, created with the tools from `create_orchestrator_tools`.

**File: `Full-Orchestrator/agents.py`**

```python
"""
Orchestrator agent: generates full infra + app from requirements and validates.
Agent is created with tools bound to output_dir and requirements (see flow.py).
"""
from crewai import Agent


def create_orchestrator_agent(tools: list) -> Agent:
    """Create the single orchestrator agent with the given tools."""
    return Agent(
        role="Full Stack DevOps Orchestrator",
        goal="Generate a complete deployment project (Terraform bootstrap, platform module, dev/prod envs, Node.js app, CodeDeploy bundle, GitHub Actions) from user requirements, then validate Terraform and Docker and write a RUN_ORDER.md with the exact command sequence for the user.",
        backstory="You are an expert DevOps engineer. You take a structured requirements input and produce a full, runnable repo: infrastructure as code, application code, deploy scripts, and CI workflows. You always generate components in the correct order (bootstrap first, then platform module, then dev then prod envs, then app and deploy and workflows), then run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod, and docker build in app, and finally write RUN_ORDER.md so the user knows the exact steps to run.",
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )
```

---

### Step 8 — Create `flow.py`

Defines the crew: one agent, one task (generate all + validate + write RUN_ORDER).

**File: `Full-Orchestrator/flow.py`**

```python
"""
Crew flow: one orchestrator agent, one task to generate and validate from requirements.
"""
from crewai import Crew, Process, Task

from agents import create_orchestrator_agent
from tools import create_orchestrator_tools


def create_orchestrator_crew(output_dir: str, requirements: dict) -> Crew:
    """
    Create a crew that:
    1. Generates bootstrap, platform, dev env, prod env, app, deploy, workflows.
    2. Validates Terraform (bootstrap, dev, prod) and Docker (app).
    3. Writes RUN_ORDER.md with the command sequence.
    """
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

---

### Step 9 — Create `run.py`

Entry point: load requirements, create output dir, create crew, kickoff, print result.

**File: `Full-Orchestrator/run.py`**

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

---

### Step 10 — Run the crew

From the **Full-Orchestrator** directory:

```bash
cd Full-Orchestrator
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
# Only if you don't have .env yet: copy .env.example .env, then set OPENAI_API_KEY
python run.py
```

Optional: `python run.py --output-dir ./my-output` or set `REQUIREMENTS_JSON` / `OUTPUT_DIR` in `.env`.

---

### Summary (chronological file order)

| Order | File               | Purpose |
|-------|--------------------|--------|
| 1     | `requirements.txt` | Python dependencies (CrewAI, requests, boto3, python-dotenv). |
| 2     | `.env.example`     | Template for `.env` (REQUIREMENTS_JSON, OUTPUT_DIR, OPENAI_API_KEY). |
| 3     | `.gitignore`       | Ignore .venv, .env, output/, __pycache__, *.pyc. |
| 4     | `requirements.json`| Input for generation (project, region, dev/prod). |
| 5     | `generators.py`    | Writes all files: bootstrap, platform, dev/prod envs, app, deploy, workflows, RUN_ORDER.md. (Full source in repo.) |
| 6     | `tools.py`         | CrewAI tools wrapping generators + terraform_validate, docker_build, write_run_order, read_file. |
| 7     | `agents.py`        | create_orchestrator_agent(tools). |
| 8     | `flow.py`          | create_orchestrator_crew(output_dir, requirements): one task (generate + validate + RUN_ORDER). |
| 9     | `run.py`           | Load requirements and .env, create crew, kickoff, print result. |

For **concepts** and **how** it works, see **EXPLANATION.md**. For more setup detail and commands, see **IMPLEMENTATION.md**.
