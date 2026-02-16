"""
CrewAI tools for the Full-Orchestrator: generate infra/app from requirements and validate.
Use create_orchestrator_tools(output_dir, requirements) to get tools bound to your run.
"""

# --- Standard library: file paths, running shell commands, JSON, type hints ---
import os          # Paths (os.path.join), directory checks (os.path.isdir, isfile).
import subprocess  # Run terraform and docker in a subprocess (subprocess.run).
import json        # Used by generators (we only need typing here; generators use json).
from typing import Any, Dict, List, Optional   # Type hints: Dict = dictionary, List = list, Optional = can be None.

# --- CrewAI @tool decorator: makes a function callable by the agent ---
# If crewai is installed, use its tool decorator (adds description for the LLM).
# If not, provide a fallback so the code still runs (e.g. in tests).
try:
    from crewai.tools import tool
except ImportError:
    def tool(desc):
        def deco(fn):
            fn.description = desc   # The LLM sees this description to decide when to call the tool.
            return fn
        return deco

# --- Import the actual generation logic from generators.py ---
# Each function writes files under output_dir using the requirements dict.
from generators import (
    generate_bootstrap,   # Writes infra/bootstrap (S3 state bucket, DynamoDB lock, KMS).
    generate_platform,    # Writes infra/modules/platform (VPC, ALB, ASG, ECR, SSM).
    generate_dev_env,     # Writes infra/envs/dev (main.tf, variables, backend.hcl, dev.tfvars).
    generate_prod_env,    # Writes infra/envs/prod (same structure).
    generate_app,        # Writes app/ (package.json, server.js, Dockerfile).
    generate_deploy,     # Writes deploy/ (appspec.yml, install/stop/start/validate scripts).
    generate_workflows,  # Writes .github/workflows (terraform-plan, build-push).
    write_run_order,     # Writes RUN_ORDER.md with the command sequence for the user.
)


def create_orchestrator_tools(output_dir: str, requirements: Dict[str, Any]) -> List[Any]:
    """
    Create tools that are bound to the given output_dir and requirements.
    The agent will call these tools; each tool uses the same output_dir and requirements.
    Returns a list of tool functions to pass to the orchestrator agent.
    """
    # Store in short names so the inner functions can use them (closure).
    out = output_dir
    req = requirements

    # --- Generation tools (no input; they just run and write files) ---

    @tool("Generate Terraform bootstrap (S3 state bucket, DynamoDB lock, KMS). No input. Writes to the configured output directory.")
    def tool_generate_bootstrap() -> str:
        """Generate Terraform bootstrap (S3 state bucket, DynamoDB lock, KMS)."""
        return generate_bootstrap(req, out)

    @tool("Generate platform Terraform module (VPC, ALB, ASG, ECR, SSM). No input. Writes to output directory.")
    def tool_generate_platform() -> str:
        """Generate platform Terraform module."""
        return generate_platform(req, out)

    @tool("Generate dev environment Terraform (main.tf, variables, backend.hcl, dev.tfvars). No input.")
    def tool_generate_dev_env() -> str:
        """Generate dev environment Terraform."""
        return generate_dev_env(req, out)

    @tool("Generate prod environment Terraform (main.tf, variables, backend.hcl, prod.tfvars). No input.")
    def tool_generate_prod_env() -> str:
        """Generate prod environment Terraform."""
        return generate_prod_env(req, out)

    @tool("Generate sample Node.js app and Dockerfile (package.json, server.js, Dockerfile). No input.")
    def tool_generate_app() -> str:
        """Generate or copy app (Node.js + Dockerfile)."""
        return generate_app(req, out)

    @tool("Generate CodeDeploy bundle (appspec.yml, install.sh, stop.sh, start.sh, validate.sh). No input.")
    def tool_generate_deploy() -> str:
        """Generate deploy bundle (CodeDeploy + Ansible)."""
        return generate_deploy(req, out)

    @tool("Generate GitHub Actions workflows (terraform-plan, build-push). No input.")
    def tool_generate_workflows() -> str:
        """Generate GitHub Actions workflows."""
        return generate_workflows(req, out)

    # --- Validation / utility tools (take input from the agent) ---

    @tool("Run 'terraform init' then 'terraform validate' in a Terraform directory. Input: path relative to output dir, e.g. 'infra/bootstrap' or 'infra/envs/dev'. Uses -backend=false so validation works without bootstrap apply. Returns validation result.")
    def tool_terraform_validate(relative_path: str) -> str:
        """Run terraform init then terraform validate in the given path. Init uses -backend=false so providers/modules are installed and validate succeeds without a real backend."""
        work_dir = os.path.join(out, relative_path)
        if not os.path.isdir(work_dir):
            return f"Error: directory not found: {work_dir}"
        try:
            # Run terraform init -backend=false -reconfigure so we never use a cached S3 backend
            # (e.g. from a previous init -backend-config=backend.hcl). Validation then works without bootstrap.
            init_result = subprocess.run(
                ["terraform", "init", "-backend=false", "-reconfigure"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if init_result.returncode != 0:
                return (
                    f"terraform init in {relative_path}: FAIL\n"
                    f"stdout: {init_result.stdout}\nstderr: {init_result.stderr}"
                )
            # Then run terraform validate.
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
            return f"Error: terraform init or validate timed out in {relative_path}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {str(e)}"

    @tool("Run 'docker build' in an app directory to validate Dockerfile. Input: path relative to output dir, e.g. 'app'. Returns build result.")
    def tool_docker_build(relative_path: str) -> str:
        """Run docker build in the given app path."""
        work_dir = os.path.join(out, relative_path)
        if not os.path.isdir(work_dir):
            return f"Error: directory not found: {work_dir}"
        try:
            # Run: docker build -t orchestrator-test:latest . in the app directory.
            result = subprocess.run(
                ["docker", "build", "-t", "orchestrator-test:latest", "."],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=300,   # Docker build can take a few minutes.
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
        """Write RUN_ORDER.md with the command sequence."""
        return write_run_order(out, extra_text or "")

    @tool("Read a file from the output directory. Input: path relative to output dir, e.g. 'infra/bootstrap/main.tf'. Returns file contents or error.")
    def tool_read_file(relative_path: str) -> str:
        """Read a file from the output directory."""
        # Full path to the file inside the output directory.
        path = os.path.join(out, relative_path)
        if not os.path.isfile(path):
            return f"Error: file not found: {path}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading {relative_path}: {type(e).__name__}: {str(e)}"

    # --- Return all tools in order (agent receives this list and can call any of them) ---
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
