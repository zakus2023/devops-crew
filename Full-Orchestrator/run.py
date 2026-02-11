#!/usr/bin/env python3
# ^ "Shebang": tells the OS to run this file with Python 3 (when you run ./run.py).

"""
Run the Full-Orchestrator: generate infra + app from requirements and validate.

Usage:
  python run.py [--output-dir DIR] [requirements.json]
  Or set REQUIREMENTS_JSON and OUTPUT_DIR in environment (or .env).

If no requirements file is given, uses requirements.json in this directory.
Output directory defaults to ./output (created if missing).
"""

# --- Standard library imports (built into Python) ---
import argparse   # Parse command-line arguments (e.g. --output-dir, requirements file path).
import json       # Read and write JSON files (our requirements.json).
import os         # Paths, environment variables, and "does this file exist?" checks.
import sys        # Access to sys.path (so we can import from this folder) and sys.exit().

# --- Make sure this script's folder is on the import path ---
# So that "from flow import ..." and "from agents import ..." work when we run python run.py.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))   # Full path to the Full-Orchestrator folder.
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)   # Add it at the front so our local modules are found first.

# --- Load environment variables from .env (optional) ---
# If python-dotenv is installed, this reads .env and sets OPENAI_API_KEY, OUTPUT_DIR, etc.
# If not installed, we skip it and rely on the shell environment.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_THIS_DIR, ".env"))   # Load from Full-Orchestrator/.env
except ImportError:
    pass   # No dotenv: continue without .env (user must set vars in shell).


def load_requirements(path: str) -> dict:
    """Read the requirements JSON file and return it as a Python dictionary."""
    with open(path, "r", encoding="utf-8") as f:   # Open file for reading, UTF-8 text.
        return json.load(f)   # Parse JSON and return the dict (project, region, dev, prod, etc.).


def main() -> int:
    """
    Entry point: figure out inputs, create the crew, run it, print the result.
    Returns 0 on success, 1 on error (so the shell can see exit code).
    """
    # --- Parse command line: optional requirements file and optional --output-dir ---
    parser = argparse.ArgumentParser(description="Full-Orchestrator: generate infra/app from requirements")
    parser.add_argument("requirements_file", nargs="?", default=None, help="Path to requirements.json")
    # nargs="?" = this argument is optional; if omitted, default is None.
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for generated project")
    args = parser.parse_args()   # Reads sys.argv (what the user typed after "python run.py").

    # --- Decide which requirements file and output directory to use ---
    # Priority: (1) command line, (2) environment variable, (3) default.
    requirements_path = args.requirements_file or os.environ.get("REQUIREMENTS_JSON") or os.path.join(_THIS_DIR, "requirements.json")
    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR") or os.path.join(_THIS_DIR, "output")

    # --- Check that the requirements file exists before we continue ---
    if not os.path.isfile(requirements_path):
        print(f"Requirements file not found: {requirements_path}")
        print("Create requirements.json or pass path. See requirements.json.example.")
        return 1   # Non-zero exit code = error (e.g. for CI scripts).

    # --- Load requirements and prepare output directory ---
    requirements = load_requirements(requirements_path)   # Dict with project, region, dev, prod.
    os.makedirs(output_dir, exist_ok=True)   # Create output dir if it doesn't exist; don't fail if it does.
    print(f"Output directory: {os.path.abspath(output_dir)}")
    print("Starting Full-Orchestrator crew...")
    print()

    # --- Create the CrewAI crew and run it ---
    from flow import create_orchestrator_crew   # Import here so .env is loaded first.
    crew = create_orchestrator_crew(output_dir=output_dir, requirements=requirements)   # One agent, one task.
    result = crew.kickoff()   # Run the crew (LLM calls the tools, generates files, validates, writes RUN_ORDER).

    # --- Print the result and tell the user what to do next ---
    print()
    print("--- Full-Orchestrator result ---")
    print(result)   # The agent's final summary (what was generated, validation status, etc.).
    print()
    print(f"Generated project is in: {os.path.abspath(output_dir)}")
    print("Next: follow RUN_ORDER.md in that directory.")
    return 0   # Success.


# --- Only run main() when this file is executed directly (not when imported) ---
if __name__ == "__main__":
    sys.exit(main())   # Run main() and exit with its return code (0 or 1).
