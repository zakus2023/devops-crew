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
