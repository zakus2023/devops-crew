"""
Combined-Crew agents: re-exported from Full-Orchestrator and Multi-Agent-Pipeline.

- create_orchestrator_agent(tools) → from Full-Orchestrator (used for the Generate task).
- infra_engineer, build_engineer, deploy_engineer, verifier_agent → from Multi-Agent-Pipeline (used for Infra, Build, Deploy, Verify tasks).

Uses importlib to avoid name collision: "from agents import X" would find this file instead of Full-Orchestrator/agents.py.
"""

# --- Standard library imports ---
# importlib.util lets us load Python files by path instead of by package name (so we can load other folders' agents.py).
import importlib.util
# os gives us path and directory operations (e.g. finding where this file lives and building paths to other folders).
import os

# --- Figure out where we are in the filesystem ---
# __file__ is the path to THIS file (agents.py). abspath() makes it a full path; dirname() gives the folder containing it.
_this_dir = os.path.dirname(os.path.abspath(__file__))
# Go up one folder from Combined-Crew to get the repo root (e.g. crew-DevOps).
_repo_root = os.path.dirname(_this_dir)
# Build the full path to the Full-Orchestrator folder (e.g. crew-DevOps/Full-Orchestrator).
_full_orch = os.path.join(_repo_root, "Full-Orchestrator")
# Build the full path to the Multi-Agent-Pipeline folder (e.g. crew-DevOps/Multi-Agent-Pipeline).
_multi_pipe = os.path.join(_repo_root, "Multi-Agent-Pipeline")

# --- Load Full-Orchestrator agents ---
# Create a "module spec" that tells Python how to load the file at Full-Orchestrator/agents.py, under a unique name so it doesn't clash with this file.
_spec_full = importlib.util.spec_from_file_location("full_orch_agents", os.path.join(_full_orch, "agents.py"))
# Create an empty module object from that spec (the module doesn't exist in memory yet).
_mod_full = importlib.util.module_from_spec(_spec_full)
# Actually run the code in Full-Orchestrator/agents.py; this executes that file and fills _mod_full with its definitions.
_spec_full.loader.exec_module(_mod_full)
# Copy the create_orchestrator_agent function from the loaded module into this module so "from agents import create_orchestrator_agent" works.
create_orchestrator_agent = _mod_full.create_orchestrator_agent

# --- Load Multi-Agent-Pipeline agents (they import "tools" from their own folder) ---
# sys gives access to the Python interpreter, including sys.path (the list of folders Python searches when you "import" something).
import sys
# Save the current search path so we can restore it later; copy() avoids modifying the original list.
_prev_path = sys.path.copy()
try:
    # Put Multi-Agent-Pipeline at the front of the search path so "import tools" finds Multi-Agent-Pipeline/tools.py.
    sys.path.insert(0, _multi_pipe)
    # Same idea as above: create a spec to load Multi-Agent-Pipeline/agents.py under a unique name.
    _spec_multi = importlib.util.spec_from_file_location("multi_pipe_agents", os.path.join(_multi_pipe, "agents.py"))
    # Create an empty module for that file.
    _mod_multi = importlib.util.module_from_spec(_spec_multi)
    # Run Multi-Agent-Pipeline/agents.py; it will import tools from Multi-Agent-Pipeline because we added that folder to sys.path.
    _spec_multi.loader.exec_module(_mod_multi)
    # Copy each agent (Role object) from the loaded module into this module so they can be imported from here.
    infra_engineer = _mod_multi.infra_engineer
    build_engineer = _mod_multi.build_engineer
    deploy_engineer = _mod_multi.deploy_engineer
    verifier_agent = _mod_multi.verifier_agent
finally:
    # Restore the original sys.path so we don't affect other code that might import after this file; "finally" runs even if an error occurred above.
    sys.path[:] = _prev_path

# __all__ defines what "from agents import *" will expose; only these names are exported when someone does a star-import.
__all__ = [
    "create_orchestrator_agent",
    "infra_engineer",
    "build_engineer",
    "deploy_engineer",
    "verifier_agent",
]
