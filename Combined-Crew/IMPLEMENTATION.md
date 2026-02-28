# Combined-Crew Gradio UI — Implementation Guide

This document describes how the Gradio UI for Combined-Crew was implemented and how to run or deploy it.

---

## Overview

The UI is a web interface built with **Gradio** that lets you:

- Upload or paste `requirements.json`
- Set output directory, production URL, AWS region
- Choose deploy method: **ansible**, **ssh_script**, or **ecs**
- For **ssh_script**: upload a PEM key or provide its path, plus AWS key pair name
- Toggle "Allow Terraform apply"
- Run the Combined-Crew with one click

---

## File Structure

| File | Purpose |
|------|---------|
| `ui.py` | Gradio app: builds the interface, wires inputs to `run_crew()` |
| `run.py` | Adds `run_crew()` for programmatic/UI use; `main()` still handles CLI |
| `requirements.txt` | Adds `gradio>=4.0.0` |
| `IMPLEMENTATION.md` | This file — technical implementation details |
| `EXPLANATION.md` | Beginner-friendly explanation |

---

## How It Works

### 1. Entry point

- `ui.py` defines a Gradio `Blocks` app with inputs and outputs.
- `run_btn.click()` connects the "Run Combined-Crew" button to `run_combined_crew()`.

### 2. Requirements handling

- User can either:
  - **Upload** a `requirements.json` file (Gradio returns the file path).
  - **Paste** JSON into the text box.
- If both are present, the uploaded file takes precedence.
- The handler loads the dict with `load_requirements(path)` or `json.loads(text)`.

### 3. Deploy method and SSH fields

- `deploy_method` is a `gr.Radio` with choices: `ansible`, `ssh_script`, `ecs`.
- The SSH group (`pem_file`, `pem_path`, `key_name`) is inside `gr.Group(visible=False)`.
- `deploy_method.change(toggle_ssh_fields, ...)` shows the SSH group only when `deploy_method == "ssh_script"`.

### 4. PEM key

- **Upload**: `gr.File(file_types=[".pem"])` returns the path to the uploaded file.
- **Path**: User types a path (e.g. `C:/path/to/key.pem`) in `pem_path`.
- The handler uses the upload path if present, otherwise the typed path. Both are passed to `run_crew(ssh_key_path=...)`.

### 5. Environment injection

- `run_crew()` in `run.py` temporarily sets:
  - `DEPLOY_METHOD`
  - `KEY_NAME` (when using ssh_script)
  - `SSH_KEY_PATH` (path to PEM)
  - `ALLOW_TERRAFORM_APPLY`
- The flow and tools read these from `os.environ`.
- `run_crew()` restores the previous env values in a `finally` block.

### 6. Execution

- `run_crew()` calls `_inject_deploy_method_into_requirements()`, `create_combined_crew()`, and `crew.kickoff()`.
- Result (success or error + traceback) is returned as a string and shown in the output `gr.Textbox`.

---

## Running Locally

### Prerequisites

- Python 3.10+
- Dependencies: `pip install -r requirements.txt` (includes Gradio)
- `.env` with `OPENAI_API_KEY` (and AWS credentials if using Terraform/ECR/deploy)

### Start the UI

```bash
cd Combined-Crew
python ui.py
```

Gradio opens a web server (default: http://127.0.0.1:7860). Open that URL in your browser.

Alternative:

```bash
gradio ui.py
```

---

## Deploying (Render / Hugging Face)

For full instructions, see **[DEPLOY.md](DEPLOY.md)**.

---

## Component Reference

### UI inputs

| Input | Type | Description |
|-------|------|-------------|
| `env_file_path` | Textbox | Path to `.env` file |
| `env_file_upload` | File | Uploaded `.env` file |
| `requirements_file` | File | Uploaded `requirements.json` |
| `requirements_json` | Textbox | Pasted JSON (fallback) |
| `output_dir` | Textbox | Output directory for generated project |
| `app_dir` | Textbox | Optional app directory (leave blank to use generated app) |
| `prod_url` | Textbox | Production URL for verify health check |
| `aws_region` | Textbox | AWS region |
| `deploy_method` | Radio | ansible \| ssh_script \| ecs |
| `allow_terraform_apply` | Checkbox | Enable Terraform apply |
| `confirm_no_apply` | Checkbox | Confirm run without Terraform apply |
| `key_name` | Textbox | AWS key pair name (ssh_script) |
| `pem_file` | File | Uploaded PEM key (ssh_script) |
| `pem_path` | Textbox | Path to PEM key (ssh_script) |
| `env_vars` | Textbox | Optional KEY=value overrides |

### `run_crew()` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `requirements` | dict or str | Requirements dict or path to JSON |
| `output_dir` | str | Output directory |
| `prod_url` | str | Production URL |
| `aws_region` | str | AWS region |
| `deploy_method` | str | ansible, ssh_script, or ecs |
| `allow_terraform_apply` | bool | Allow Terraform apply |
| `key_name` | str | AWS key pair name |
| `ssh_key_path` | str | Path to PEM file |
| `ssh_key_content` | str or None | PEM content (alternative to path) |
| `app_dir` | str or None | Optional app directory for Docker build |

---

## Troubleshooting

- **"Provide requirements.json or paste JSON"** — At least one of the file upload or JSON text box must be filled.
- **"Invalid JSON"** — Check the pasted JSON syntax (commas, brackets, quotes).
- **"PEM key file not found"** — The path in `pem_path` must exist; on Windows use forward slashes or escaped backslashes.
- **OpenAI errors** — Ensure `OPENAI_API_KEY` is set in `.env` or environment.
- **AWS/Terraform errors** — Ensure AWS credentials and region are configured.
