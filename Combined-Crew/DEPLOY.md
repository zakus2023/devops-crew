# Deploy DevOps-Crew on Hugging Face Spaces

Run the pipeline UI (Generate → Infra → Build → Deploy → Verify) on Hugging Face Spaces. Users provide their own OpenAI and AWS credentials in the app; the Space owner does not expose shared keys.

---

## Architecture

DevOps-Crew uses **two Hugging Face repos**:

| Repo | Purpose | Contents |
|------|---------|----------|
| **Model** | Project code (downloaded at runtime) | Combined-Crew, Full-Orchestrator, Multi-Agent-Pipeline, infra |
| **Space** | App entry point (thin wrapper) | app.py, requirements.txt, Dockerfile, README |

The Space container starts, fetches the project from the model repo, then runs the Gradio UI. No Docker socket is available, so the Build step uses the **EC2 build runner** or **pre-built images** (see [Build step](#build-step-no-docker)).

---

## Prerequisites

- [Hugging Face](https://huggingface.co) account
- [GitHub](https://github.com) account (optional; for workflows)
- OpenAI API key and AWS credentials (each user supplies their own in the UI)

---

## Setup

### 1. Create the model repo

1. Go to [huggingface.co/new](https://huggingface.co/new)
2. Choose **Model**
3. Name it (e.g. `crew-devops`)

### 2. Create the Space

1. Go to [huggingface.co/spaces](https://huggingface.co/spaces)
2. Click **Create new Space**
3. **SDK:** Docker (recommended; includes Terraform CLI)
4. **Space hardware:** CPU basic (free tier)

### 3. Upload project files to the model repo

From the project root:

```bash
export HF_TOKEN="hf_your_token"
export HF_REPO="your-username/crew-devops"   # or HF_MODEL
python Combined-Crew/scripts/upload-for-hf.py
```

### 4. Upload the Space app

```bash
export HF_SPACE="your-username/crew-devops"
export HF_MODEL="your-username/crew-devops"
python Combined-Crew/scripts/upload-space-app.py
```

### 5. Configure Space variables

In **Settings → Variables and secrets**, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `DEVOPS_CREW_MODEL` | `your-username/crew-devops` | Model repo the Space fetches from |
| `HF_TOKEN` | Your HF token | Required for private model; Read role is enough |

**Do not** add `OPENAI_API_KEY` or AWS keys here — users enter them in the app UI.

### 6. Build and run

The Space builds from the Dockerfile (first build ~5–10 min). When it’s done, open the Space URL, expand **Environment variables** in the UI, add your credentials, and run the pipeline.

---

## Credentials

Each run uses credentials from the app’s **Environment variables** section (one per line, `KEY=value`):

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | [platform.openai.com](https://platform.openai.com) |
| `AWS_ACCESS_KEY_ID` | No | Terraform, ECR, deploy |
| `AWS_SECRET_ACCESS_KEY` | No | |
| `PRE_BUILT_IMAGE_TAG` | No | When Build can’t run Docker: use a tag from GitHub Actions or `ecr_list_image_tags` |

---

## Updating after code changes

1. `python Combined-Crew/scripts/upload-for-hf.py` → model repo
2. `python Combined-Crew/scripts/upload-space-app.py` → Space
3. Space → **Settings** → **Factory reboot**

---

## CLI upload (without scripts)

```bash
pip install "huggingface_hub[cli]"
export HF_TOKEN="hf_xxx"
REPO="YOUR_USERNAME/crew-devops"

# Model repo (project files)
python -m huggingface_hub.commands.huggingface_cli upload $REPO ./Combined-Crew Combined-Crew --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload $REPO ./Full-Orchestrator Full-Orchestrator --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload $REPO ./Multi-Agent-Pipeline Multi-Agent-Pipeline --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload $REPO ./infra infra --repo-type=model --exclude ".terraform*" --exclude "__pycache__*"

# Space: use upload-space-app.py (copies space_app.py → app.py, creates README, uploads Dockerfile)
```

---

## Build step (no Docker)

Spaces run in containers without a Docker socket. When the Build step can’t run `docker build`:

1. **EC2 build runner** — The agent uses `ec2_docker_build_and_push`: zips the app, uploads to S3, runs an SSM command on the EC2 build runner to build and push, then updates SSM.
2. **Pre-built image** — Build locally, then set `PRE_BUILT_IMAGE_TAG` in the UI, or let the agent use `ecr_list_image_tags` + `write_ssm_image_tag`.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "OPENAI_API_KEY required" | Expand **Environment variables** in the UI and add `OPENAI_API_KEY=sk-...` |
| Exceeded memory limit | Free tier has 512 MB. Restarts are automatic. For repeated failures, run locally (`python ui.py`) for heavy workloads. |
| Build fails (docker not found) | Expected. Use EC2 build runner or set `PRE_BUILT_IMAGE_TAG` with a pre-built image. |
| 401 / Repository Not Found | Add `HF_TOKEN` in Space Settings and ensure `DEVOPS_CREW_MODEL` matches the model repo name. |
| Module not found | Ensure Combined-Crew, Full-Orchestrator, Multi-Agent-Pipeline, and infra are in the model repo. |
| App not deployed | Terraform apply must complete. Set `DEPLOY_METHOD` to match your infra (ansible / ssh_script / ecs). |
| "No such file or directory: ssh" | Space Dockerfile includes `openssh-client` for ssh_script deploy. Rebuild the Space. |
| SSH deploy fails (Connection refused) | Set `SSH_KEY_PATH` or `SSH_PRIVATE_KEY` in UI env vars. For private EC2s, set `BASTION_HOST` to bastion public IP. |
