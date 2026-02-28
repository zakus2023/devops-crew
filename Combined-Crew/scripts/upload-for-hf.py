#!/usr/bin/env python3
"""
Copy Combined-Crew, Full-Orchestrator, Multi-Agent-Pipeline, and infra to a temp
dir excluding .venv, .terraform, etc., then upload to Hugging Face model repo.
The infra folder contains the full platform Terraform module; without it, the
generator uses a minimal placeholder and Terraform validate fails.
Uses --repo-type=model. The Space loads from the model at runtime (space_app.py).
"""
import os
import shutil
import subprocess
import sys
import tempfile

EXCLUDE = {".venv", ".env", "output", ".terraform", "__pycache__", ".git"}
REPO_TYPE = "model"  # Project files go to model repo; Space has only app.py


def should_ignore(path, names):
    return [n for n in names if n in EXCLUDE or n.endswith(".exe")]


def main():
    repo_id = os.environ.get("HF_REPO") or os.environ.get("HF_MODEL", "idbsch2012/crew-devops")
    if not os.environ.get("HF_TOKEN"):
        print("Set HF_TOKEN first: export HF_TOKEN='hf_xxx'")
        sys.exit(1)

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with tempfile.TemporaryDirectory() as tmp:
        for folder in ["Combined-Crew", "Full-Orchestrator", "Multi-Agent-Pipeline"]:
            src = os.path.join(base, folder)
            dst = os.path.join(tmp, folder)
            if os.path.isdir(src):
                print(f"Copying {folder} (excluding .venv, .env, output, .terraform)...")
                shutil.copytree(src, dst, ignore=should_ignore, dirs_exist_ok=True)
                print(f"  -> {dst}")

        # Include infra (platform module) so Full-Orchestrator can copy full module instead of placeholder
        infra_src = os.path.join(base, "infra")
        infra_dst = os.path.join(tmp, "infra")
        if os.path.isdir(infra_src):
            print("Copying infra (excluding .terraform)...")
            shutil.copytree(infra_src, infra_dst, ignore=should_ignore, dirs_exist_ok=True)
            print(f"  -> {infra_dst}")
        else:
            print("Note: infra/ not found; platform module will use minimal placeholder.")

        readme = os.path.join(base, "README.md")
        if os.path.isfile(readme):
            shutil.copy2(readme, os.path.join(tmp, "README.md"))
            print("Copied README.md")

        req_src = os.path.join(base, "Combined-Crew", "requirements.txt")
        if os.path.isfile(req_src):
            shutil.copy2(req_src, os.path.join(tmp, "requirements.txt"))
            print("Copied requirements.txt")

        for folder in ["Combined-Crew", "Full-Orchestrator", "Multi-Agent-Pipeline"]:
            src = os.path.join(tmp, folder)
            if os.path.isdir(src):
                print(f"Uploading {folder}...")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "huggingface_hub.commands.huggingface_cli",
                        "upload",
                        repo_id,
                        src,
                        folder,
                        f"--repo-type={REPO_TYPE}",
                    ],
                    check=True,
                )

        if os.path.isdir(infra_dst):
            print("Uploading infra...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "huggingface_hub.commands.huggingface_cli",
                    "upload",
                    repo_id,
                    infra_dst,
                    "infra",
                    f"--repo-type={REPO_TYPE}",
                ],
                check=True,
            )

        readme_dst = os.path.join(tmp, "README.md")
        if os.path.isfile(readme_dst):
            print("Uploading README.md...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "huggingface_hub.commands.huggingface_cli",
                    "upload",
                    repo_id,
                    readme_dst,
                    "README.md",
                    f"--repo-type={REPO_TYPE}",
                ],
                check=True,
            )

        req_dst = os.path.join(tmp, "requirements.txt")
        if os.path.isfile(req_dst):
            print("Uploading requirements.txt...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "huggingface_hub.commands.huggingface_cli",
                    "upload",
                    repo_id,
                    req_dst,
                    "requirements.txt",
                    f"--repo-type={REPO_TYPE}",
                ],
                check=True,
            )

    print("Done.")
    print("See Combined-Crew/DEPLOY.md for full deployment guide.")


if __name__ == "__main__":
    main()
