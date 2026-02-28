# Combined-Crew

**One crew:** Generate a full project from requirements (**Full-Orchestrator**) then run the deploy pipeline (**Multi-Agent-Pipeline**) on the generated output.

**Flow:** Generate → Infra → Build → Deploy → Verify (5 tasks in sequence).

Requires **Full-Orchestrator** and **Multi-Agent-Pipeline** as sibling folders.

---

## Quick start

```bash
cd Combined-Crew
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env           # set OPENAI_API_KEY; optional: PROD_URL, ALLOW_TERRAFORM_APPLY, DEPLOY_METHOD
python run.py
```

Or with UI: `python ui.py` (Gradio at http://127.0.0.1:7860).

---

## Deploy (hosted UI)

| Platform | Guide |
|----------|-------|
| **Render** (free tier) | [DEPLOY.md#render](DEPLOY.md#render) |
| **Hugging Face Spaces** | [DEPLOY.md#hugging-face](DEPLOY.md#hugging-face) |

---

## Docs

| File | Purpose |
|------|---------|
| [EXPLANATION.md](EXPLANATION.md) | How it works, concepts |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Gradio UI implementation |
| [DEPLOY.md](DEPLOY.md) | Render + Hugging Face deployment |
