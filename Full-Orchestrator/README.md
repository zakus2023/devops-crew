# Full-Orchestrator

Generate a **full deployment project** (Terraform, Node.js app, CodeDeploy, GitHub Actions) from **requirements.json** using CrewAI.

---

## Quick start

```bash
cd Full-Orchestrator
python -m venv .venv
source .venv/Scripts/activate   # Bash; Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # set OPENAI_API_KEY
python run.py
```

Then follow **RUN_ORDER.md** in `output/`.

---

## Docs

| File | Purpose |
|------|---------|
| [EXPLANATION.md](EXPLANATION.md) | Concepts, how it works |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Step-by-step implementation reference |
