# Multi-Agent Deploy Pipeline

Run **Terraform → Build → Deploy → Verify** on a deployment project using four CrewAI agents.

**REPO_ROOT:** Path to the deployment project (e.g. Full-Orchestrator/output). When in crew-DevOps, defaults to CICD-With-AI or generated output.

---

## Quick start

```bash
cd Multi-Agent-Pipeline
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env         # PROD_URL, OPENAI_API_KEY; optional: DEPLOY_METHOD, SSH_KEY_PATH
python run.py
```

**Deploy methods:** `ansible` | `ssh_script` | `ecs` (set `DEPLOY_METHOD` in .env).  
**Terraform apply:** Set `ALLOW_TERRAFORM_APPLY=1` to allow apply (default: plan only).

---

## ssh_script deploy (quick path)

1. Set `DEPLOY_METHOD=ssh_script` in .env
2. Set `SSH_KEY_PATH` to full path of your `.pem` file
3. Ensure EC2 instances have tag **Env=prod** (or Env=dev)
4. For private subnets: set `enable_bastion=true`, `key_name` in prod.tfvars
5. Run `python run.py`

---

## Docs

| File | Purpose |
|------|---------|
| [EXPLANATION.md](EXPLANATION.md) | Concepts, how it works |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Setup, deploy options, ssh_script details |
