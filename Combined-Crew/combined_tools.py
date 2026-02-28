"""
Combined-Crew tools: re-exported from Full-Orchestrator and Multi-Agent-Pipeline.

From Full-Orchestrator:
- create_orchestrator_tools(output_dir, requirements) → returns list of tools for the Generate task.

From Multi-Agent-Pipeline:
- set_repo_root(path) → sets the repo root for pipeline tools so they run in the generated output_dir.

Named combined_tools to avoid collision with "tools" (Multi-Agent-Pipeline/agents imports from tools).
"""
import importlib.util
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_this_dir)
_full_orch = os.path.join(_repo_root, "Full-Orchestrator")
_multi_pipe = os.path.join(_repo_root, "Multi-Agent-Pipeline")

# Load Full-Orchestrator tools (depends on generators - need Full-Orchestrator in path)
_prev_path = sys.path.copy()
try:
    sys.path.insert(0, _full_orch)
    _spec_full = importlib.util.spec_from_file_location("full_orch_tools", os.path.join(_full_orch, "tools.py"))
    _mod_full = importlib.util.module_from_spec(_spec_full)
    _spec_full.loader.exec_module(_mod_full)
    create_orchestrator_tools = _mod_full.create_orchestrator_tools
finally:
    sys.path[:] = _prev_path

# Load Multi-Agent-Pipeline set_repo_root (self-contained)
_spec_multi = importlib.util.spec_from_file_location("multi_pipe_tools", os.path.join(_multi_pipe, "tools.py"))
_mod_multi = importlib.util.module_from_spec(_spec_multi)
_spec_multi.loader.exec_module(_mod_multi)
set_repo_root = _mod_multi.set_repo_root
set_app_root = getattr(_mod_multi, "set_app_root", None)
set_project = getattr(_mod_multi, "set_project", None)

__all__ = ["create_orchestrator_tools", "set_repo_root", "set_app_root", "set_project"]
