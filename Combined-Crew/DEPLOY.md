# Deploy DevOps-Crew (Render & Hugging Face)

Host the pipeline UI (Generate → Infra → Build → Deploy → Verify) on Render or Hugging Face Spaces.

| Platform | Deploy | Free tier | Build step (no Docker) |
|----------|--------|-----------|------------------------|
| **Render** | GitHub → Blueprint | Yes (sleeps ~15 min) | CodeBuild or pre-built image |
| **Hugging Face** | Model repo + Space | Yes | Same |

**Shared:** Both platforms run in containers without Docker socket. Use **CodeBuild** or **pre-built images** (GitHub Actions / local build + `PRE_BUILT_IMAGE_TAG` or `ecr_list_image_tags`).

---

## Credentials (all platforms)

Users provide their own in the UI (Environment variables):

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | [platform.openai.com](https://platform.openai.com) |
| `AWS_ACCESS_KEY_ID` | No | Terraform, ECR, deploy |
| `AWS_SECRET_ACCESS_KEY` | No | |
| `PRE_BUILT_IMAGE_TAG` | No | When Build can't run Docker: tag from GitHub Actions or `ecr_list_image_tags` |

---

## Render

**Prerequisites:**

- [Render](https://render.com) account
- [GitHub](https://github.com) account
- OpenAI API key (required for CrewAI)
- AWS credentials (optional; for Terraform, ECR, deploy)

---

### Step 1: Push the project to GitHub

1. Create a new repository on GitHub (e.g. `crew-devops`).
2. Clone or add it as a remote to your local project:

```bash
cd /path/to/crew-DevOps
git remote add origin https://github.com/YOUR_USERNAME/crew-devops.git
```

3. Ensure these files and folders are in the repo:

| Path | Required |
|------|----------|
| `render.yaml` | Yes (at repo root) |
| `Dockerfile` | Yes (at repo root) |
| `Combined-Crew/` | Yes |
| `Full-Orchestrator/` | Yes |
| `Multi-Agent-Pipeline/` | Yes |
| `infra/` | Yes |

4. Commit and push:

```bash
git add .
git commit -m "Add Render deployment"
git push -u origin main
```

---

### Step 2: Create a Render account

1. Go to [render.com](https://render.com) and sign up (or log in).
2. Connect your GitHub account when prompted (Settings → Account → Integrations).

---

### Step 3: Create a Blueprint

1. Go to [dashboard.render.com](https://dashboard.render.com).
2. Click **New** → **Blueprint**.
3. Connect your GitHub account if not already connected.
4. Select the repository (e.g. `crew-devops`).
5. Render detects `render.yaml` — you should see the `crew-devops` web service.
6. Click **Apply** to create the service.

---

### Step 4: Set environment variables

1. In the Render dashboard, open your **crew-devops** service.
2. Go to **Environment** (left sidebar).
3. Add these variables (click **Add Environment Variable**):

| Key | Value | Required |
|-----|-------|----------|
| `OPENAI_API_KEY` | `sk-your-openai-key` | Yes |
| `AWS_ACCESS_KEY_ID` | Your AWS access key | No |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key | No |

**Optional:** `AWS_REGION` (default `us-east-1`), `PRE_BUILT_IMAGE_TAG` (when Build can't run Docker).

4. Click **Save Changes**. Render will redeploy automatically.

---

### Step 5: Wait for the first deploy

1. Render builds the Docker image (first build may take 5–10 minutes).
2. Watch the **Logs** tab for progress.
3. When the build completes, the service URL will be active (e.g. `https://crew-devops.onrender.com`).

---

### Step 6: Use the app

1. Open the service URL in your browser.
2. In the UI:
   - Upload or paste `requirements.json`
   - Set output directory (default `./output`), deploy method, and options
   - Expand **Environment variables** to add any extra keys (e.g. `PRE_BUILT_IMAGE_TAG`)
   - Click **Run Combined-Crew**
3. After the pipeline completes, click **Download output** to save the generated zip.

---

### Free tier notes

- **Sleep:** Service sleeps after ~15 minutes of inactivity. The first request after sleep may take 30–60 seconds to wake.
- **Build minutes:** Free tier has limited build minutes per month.
- **Output:** Output is ephemeral; use **Download output** before the service sleeps or restarts.

---

### Redeploy after code changes

Push to the connected branch (e.g. `main`):

```bash
git add .
git commit -m "Your changes"
git push
```

Render auto-deploys on push. Or use **Manual Deploy** in the dashboard.

---

## Hugging Face

**Architecture:** Project files in **model repo**. **Space** has only `app.py` — downloads project at runtime.

| Repo | Contents |
|------|----------|
| **Model** | Combined-Crew, Full-Orchestrator, Multi-Agent-Pipeline, infra |
| **Space** | app.py, requirements.txt, Dockerfile, README |

### Steps

1. **Create model repo** — [huggingface.co/new](https://huggingface.co/new) → Model, e.g. `crew-devops`.
2. **Create Space** — [huggingface.co/spaces](https://huggingface.co/spaces) → Create → SDK: **Gradio** or **Docker** (Docker recommended for Terraform).
3. **Upload to model repo** — use script or CLI:

```bash
export HF_TOKEN="hf_your_token"
export HF_REPO="your-username/crew-devops"   # or HF_MODEL
python Combined-Crew/scripts/upload-for-hf.py
```

4. **Upload Space app** — `app.py` (from `space_app.py`), requirements.txt, Dockerfile, README:

```bash
export HF_SPACE="your-username/crew-devops"
export HF_MODEL="your-username/crew-devops"
python Combined-Crew/scripts/upload-space-app.py
```

5. **Space variables** (Settings → Variables and secrets):
   - `DEVOPS_CREW_MODEL` = `your-username/crew-devops`
   - `HF_TOKEN` = your token (Read role; required for private model)

6. **Use** — open Space URL, run pipeline, download output.

### Deployment checklist (after code changes)

1. `upload-for-hf.py` → model repo
2. `upload-space-app.py` → Space
3. Restart Space (Factory reboot)

### CLI upload (no script)

```bash
pip install "huggingface_hub[cli]"
export HF_TOKEN="hf_xxx"

# Model repo (project files)
python -m huggingface_hub.commands.huggingface_cli upload YOUR_USERNAME/crew-devops ./Combined-Crew Combined-Crew --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload YOUR_USERNAME/crew-devops ./Full-Orchestrator Full-Orchestrator --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload YOUR_USERNAME/crew-devops ./Multi-Agent-Pipeline Multi-Agent-Pipeline --repo-type=model --exclude ".env" --exclude "**/.env" --exclude ".venv*" --exclude "**/output*" --exclude ".terraform*" --exclude "__pycache__*"
python -m huggingface_hub.commands.huggingface_cli upload YOUR_USERNAME/crew-devops ./infra infra --repo-type=model --exclude ".terraform*" --exclude "__pycache__*"

# Space (app entry point)
# Use upload-space-app.py or copy space_app.py → app.py and upload
```

---

## Build step (no Docker)

When `docker build` fails (HF/Render containers lack Docker socket):

1. **CodeBuild** — `codebuild_build_and_push` zips app, uploads to S3, runs AWS CodeBuild, updates SSM.
2. **Pre-built** — Build locally or via `.github/workflows/build-push.yml`, then set `PRE_BUILT_IMAGE_TAG` or let agent use `ecr_list_image_tags` + `write_ssm_image_tag`.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "OPENAI_API_KEY required" | Add in UI Environment variables |
| Build fails (docker not found) | Expected. Use CodeBuild or pre-built image |
| 401 / Repository Not Found (HF) | Add `HF_TOKEN` in Space Settings; ensure `DEVOPS_CREW_MODEL` matches model repo |
| Module not found | Ensure Full-Orchestrator, Multi-Agent-Pipeline, infra in model/repo |
| App not deployed | Terraform apply must complete; set `DEPLOY_METHOD` to match infra (ecs/ssh_script/ansible) |
