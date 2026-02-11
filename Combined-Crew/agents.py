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
