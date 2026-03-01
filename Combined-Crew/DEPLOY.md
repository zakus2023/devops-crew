# Deploy DevOps-Crew (Render & Hugging Face)

Host the pipeline UI (Generate → Infra → Build → Deploy → Verify) on Render or Hugging Face Spaces.

| Platform | Deploy | Free tier | Build step (no Docker) |
|----------|--------|-----------|------------------------|
| **Render** | GitHub → Blueprint | Yes (sleeps ~15 min) | CodeBuild or pre-built image |
| **Hugging Face** | Model repo + Space | Yes | Same |

**Shared:** Both platforms run in containers without Docker socket. Use **CodeBuild** or **pre-built images** (GitHub Actions / local build + `PRE_BUILT_IMAGE_TAG` or `ecr_list_image_tags`).

---

## Credentials (all platforms)

**Do not share API keys.** Each user provides their own credentials in the app UI.

When running the pipeline, expand **Environment variables** in the UI and enter (one per line, `KEY=value`):

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | [platform.openai.com](https://platform.openai.com) |
| `AWS_ACCESS_KEY_ID` | No | Terraform, ECR, deploy |
| `AWS_SECRET_ACCESS_KEY` | No | |
| `PRE_BUILT_IMAGE_TAG` | No | When Build can't run Docker: tag from GitHub Actions or `ecr_list_image_tags` |

**Render / Hugging Face owner:** Leave dashboard Environment/Settings empty. Do not add your keys there for shared deployments — users supply theirs in the UI.

---

## Render

**Prerequisites:**

- [Render](https://render.com) account
- [GitHub](https://github.com) account
- (Users provide their own OpenAI API key and AWS credentials in the app UI)

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

### Step 4: Environment (leave empty for shared use)

**Leave the Render dashboard Environment empty.** Users provide their own `OPENAI_API_KEY` and AWS credentials in the app UI when they run the pipeline (see Step 6).

If you are the sole user and prefer to set keys once, you can add them in **Environment** → **Add Environment Variable**. For shared deployments, do not add keys — each user enters theirs in the UI.

---

### Step 5: Wait for the first deploy

1. Render builds the Docker image (first build may take 5–10 minutes).
2. Watch the **Logs** tab for progress.
3. When the build completes, the service URL will be active (e.g. `https://crew-devops.onrender.com`).

---

### Step 6: Use the app

1. Open the service URL in your browser.
2. **Expand "Environment variables"** and add your credentials (one per line):
   ```
   OPENAI_API_KEY=sk-your-openai-key
   AWS_ACCESS_KEY_ID=your-access-key
   AWS_SECRET_ACCESS_KEY=your-secret-key
   ```
3. Upload or paste `requirements.json`, set output directory, deploy method, and options.
4. Click **Run Combined-Crew**.
5. After the pipeline completes, click **Download output** to save the generated zip.

---

### Free tier notes

- **Sleep:** Service sleeps after ~15 minutes of inactivity. The first request after sleep may take 30–60 seconds to wake.
- **Build minutes:** Free tier has limited build minutes per month.
- **Output:** Output is ephemeral; use **Download output** before the service sleeps or restarts.
- **Memory:** Free tier has 512 MB RAM. The image is optimized (no Docker CLI; Build uses CodeBuild). If you hit memory limits, see [Memory limits](#memory-limits).

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

### Memory limits

Free tier (512 MB) is supported. The image is optimized: Docker CLI omitted (Build uses CodeBuild), and memory is freed after each run. If you see **"Web Service exceeded its memory limit"**:

1. **Try again** — Restarts are automatic; the next run may succeed.
2. **Run locally for heavy workloads** — `python ui.py` on your machine for full pipeline runs.
3. **Upgrade if needed** — Render dashboard → **Settings** → **Instance Type** → **Standard** (2 GB, $25/mo).

| Instance | RAM | Cost |
|----------|-----|------|
| Free | 512 MB | $0 |
| Standard | 2 GB | $25/mo |

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

5. **Space variables** (Settings → Variables and secrets) — deployment config only (not user credentials):
   - `DEVOPS_CREW_MODEL` = `your-username/crew-devops`
   - `HF_TOKEN` = your token (Read role; required for private model)
   - Leave `OPENAI_API_KEY` and AWS keys empty — users provide theirs in the app UI.

6. **Use** — open Space URL, expand **Environment variables** in the UI, add your `OPENAI_API_KEY` and AWS keys, then run pipeline and download output.

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
| "OPENAI_API_KEY required" | Expand **Environment variables** in the UI and add `OPENAI_API_KEY=sk-...` |
| Exceeded memory limit (Render) | Free tier is supported; restarts are automatic. For repeated failures, upgrade to **Standard** (2 GB) in Settings → Instance Type. |
| Build fails (docker not found) | Expected. Use CodeBuild or pre-built image |
| 401 / Repository Not Found (HF) | Add `HF_TOKEN` in Space Settings; ensure `DEVOPS_CREW_MODEL` matches model repo |
| Module not found | Ensure Full-Orchestrator, Multi-Agent-Pipeline, infra in model/repo |
| App not deployed | Terraform apply must complete; set `DEPLOY_METHOD` to match infra (ecs/ssh_script/ansible) |
