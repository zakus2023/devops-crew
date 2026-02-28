"""
Space entry point. Downloads the project from the model repo at runtime.
Users only see this app — project files stay in the model repo (hidden from Space Files tab).

Required: DEVOPS_CREW_MODEL (Space variable) = your model repo, e.g. username/crew-devops
For private model repos: add HF_TOKEN in Space Settings → Variables and secrets.
"""
import os
import sys

_model_id = os.environ.get("DEVOPS_CREW_MODEL", "idbsch2012/crew-devops")
_token = os.environ.get("HF_TOKEN")
from huggingface_hub import snapshot_download

_path = snapshot_download(repo_id=_model_id, repo_type="model", token=_token)
_combined = os.path.join(_path, "Combined-Crew")
sys.path.insert(0, _combined)
os.chdir(_combined)

from ui import build_ui

demo = build_ui()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
