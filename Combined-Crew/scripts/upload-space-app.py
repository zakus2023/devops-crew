#!/usr/bin/env python3
"""
Upload the minimal Space app (app.py, requirements.txt) to a Hugging Face Space.
The Space loads the full project from the model repo at runtime.

Usage:
  export HF_TOKEN="hf_xxx"
  export HF_SPACE="your-username/crew-devops"
  export HF_MODEL="your-username/crew-devops"   # for DEVOPS_CREW_MODEL
  python Combined-Crew/scripts/upload-space-app.py
"""
import os
import subprocess
import sys
import tempfile

def main():
    space_id = os.environ.get("HF_SPACE", "idbsch2012/crew-devops")
    model_id = os.environ.get("HF_MODEL", "idbsch2012/crew-devops")
    if not os.environ.get("HF_TOKEN"):
        print("Set HF_TOKEN first: export HF_TOKEN='hf_xxx'")
        sys.exit(1)
    print(f"Space (app entry point): {space_id}")
    print(f"Model (code; DEVOPS_CREW_MODEL): {model_id}")

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    combined = os.path.join(base, "Combined-Crew")

    with tempfile.TemporaryDirectory() as tmp:
        # Copy space_app.py as app.py
        space_app = os.path.join(combined, "space_app.py")
        app_py = os.path.join(tmp, "app.py")
        if os.path.isfile(space_app):
            with open(space_app) as f:
                content = f.read()
            with open(app_py, "w") as f:
                f.write(content)
            print("Prepared app.py from space_app.py")
        else:
            print("Error: Combined-Crew/space_app.py not found")
            sys.exit(1)

        # Copy requirements.txt
        req_src = os.path.join(combined, "requirements.txt")
        req_dst = os.path.join(tmp, "requirements.txt")
        if os.path.isfile(req_src):
            with open(req_src) as f:
                content = f.read()
            with open(req_dst, "w") as f:
                f.write(content)
            print("Prepared requirements.txt")

        # Create Space README with YAML (sdk: docker for Terraform support)
        readme_dst = os.path.join(tmp, "README.md")
        readme_content = """---
title: DevOps-Crew
sdk: docker
app_port: 7860
---

# DevOps-Crew

Generate → Infra → Build → Deploy → Verify from requirements.json.
Includes Terraform CLI for full Infra step.
"""
        with open(readme_dst, "w", encoding="utf-8") as f:
            f.write(readme_content)
        print("Prepared README.md")

        # Copy Dockerfile (uses Terraform + Python)
        dockerfile_src = os.path.join(combined, "Dockerfile")
        if os.path.isfile(dockerfile_src):
            dockerfile_dst = os.path.join(tmp, "Dockerfile")
            with open(dockerfile_src) as f:
                content = f.read()
            with open(dockerfile_dst, "w") as f:
                f.write(content)
            print("Prepared Dockerfile")

        # Upload app.py
        print(f"Uploading app.py to Space {space_id}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "huggingface_hub.commands.huggingface_cli",
                "upload",
                space_id,
                app_py,
                "app.py",
                "--repo-type=space",
            ],
            check=True,
        )

        # Upload requirements.txt
        print(f"Uploading requirements.txt to Space {space_id}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "huggingface_hub.commands.huggingface_cli",
                "upload",
                space_id,
                req_dst,
                "requirements.txt",
                "--repo-type=space",
            ],
            check=True,
        )

        # Upload README.md
        print(f"Uploading README.md to Space {space_id}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "huggingface_hub.commands.huggingface_cli",
                "upload",
                space_id,
                readme_dst,
                "README.md",
                "--repo-type=space",
            ],
            check=True,
        )

        # Upload Dockerfile
        dockerfile_dst = os.path.join(tmp, "Dockerfile")
        if os.path.isfile(dockerfile_dst):
            print(f"Uploading Dockerfile to Space {space_id}...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "huggingface_hub.commands.huggingface_cli",
                    "upload",
                    space_id,
                    dockerfile_dst,
                    "Dockerfile",
                    "--repo-type=space",
                ],
                check=True,
            )

    print("Done.")
    print(f"\nSpace variables (Settings → Variables and secrets):")
    print(f"  DEVOPS_CREW_MODEL={model_id}")
    print(f"  HF_TOKEN=<your token> (required for private model repo)")
    print(f"\nThe Space uses sdk: docker with Terraform. First build may take 5–10 minutes.")
    print("See Combined-Crew/DEPLOY.md for full deployment guide.")

if __name__ == "__main__":
    main()
