#!/usr/bin/env python3
"""
Gradio UI for Combined-Crew: run Generate → Infra → Build → Deploy → Verify from a web interface.

Usage:
  python ui.py
  # Or: gradio ui.py

Then open the URL shown (default http://127.0.0.1:7860).
"""
import json
import os
import sys

# Disable CrewAI telemetry to avoid "signal only works in main thread" when running in Gradio worker thread
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Load default .env at startup (can be overridden via UI)
if load_dotenv:
    load_dotenv(os.path.join(_THIS_DIR, ".env"))

import gradio as gr

# Full .env template showing required and optional variables (commented = not applied)
ENV_TEMPLATE = """# --- Required (uncomment and fill) ---
# OPENAI_API_KEY=sk-your-openai-key-here

# --- AWS (required for Terraform, ECR, deploy) ---
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
# AWS_REGION=us-east-1
# AWS_PROFILE=

# --- Run options (optional; many have dedicated UI inputs) ---
# OUTPUT_DIR=./output
# PROD_URL=
# REQUIREMENTS_JSON=
# ALLOW_TERRAFORM_APPLY=1
# DEPLOY_METHOD=ansible
# APP_ROOT=

# --- SSH / Bastion (for deploy method: ssh_script) ---
# KEY_NAME=
# SSH_KEY_PATH=
# SSH_PRIVATE_KEY=
# BASTION_HOST=
# BASTION_USER=ec2-user

# --- Ansible ---
# ANSIBLE_WAIT_BEFORE_DEPLOY=0
# ANSIBLE_USE_WSL=1
"""

# Lazy import: defer run/destroy to avoid loading CrewAI (and requiring OPENAI_API_KEY) at startup


def toggle_ssh_fields(method):
    """Show SSH fields only when deploy method is ssh_script."""
    return gr.update(visible=(method == "ssh_script"))


def toggle_deploy_method_ansible(method, output_dir):
    """When ansible: uncheck and disable Terraform apply; show procedure. Otherwise: enable apply, hide procedure."""
    is_ansible = (method or "").strip().lower() == "ansible"
    out = (output_dir or "").strip() or "./output"
    procedure_md = _ansible_procedure_md(out) if is_ansible else ""
    return (
        gr.update(value=False, interactive=not is_ansible),  # allow_terraform_apply
        gr.update(visible=is_ansible),  # ansible_procedure_group
        procedure_md,  # ansible_procedure_md
    )


def toggle_terraform_confirm(allow_apply):
    """Show Terraform confirmation only when apply is disabled."""
    return gr.update(visible=not allow_apply)


MSG_TERRAFORM_NO_APPLY_CONFIRM = (
    "⚠️ **Terraform apply is disabled.** Please confirm:\n\n"
    "**If you continue (plan only):**\n"
    "• Terraform will run init and plan only — no infrastructure will be created or modified\n"
    "• You'll see what would change, but nothing will be provisioned\n"
    "• Build, Deploy, and Verify steps may fail (no infra to deploy to)\n\n"
    "**To continue with plan only:** Check \"I confirm: run without Terraform apply\" and click Run again.\n\n"
    "**To create infrastructure:** Check \"Allow Terraform apply\" and click Run. "
    "Terraform will apply and create/update bootstrap, dev, and prod resources (VPC, ECR, EC2/ECS, etc.)."
)

def _ansible_procedure_md(output_dir: str) -> str:
    """Step-by-step procedure when Ansible deploy method is selected."""
    out = (output_dir or "").strip() or "./output"
    return f"""
**Operating system:** Run these commands on **Linux**, **macOS**, or **Windows (WSL recommended)**.  
On Windows without WSL, use PowerShell or Git Bash; set `ANSIBLE_USE_WSL=0` in .env if needed.

**Step-by-step procedure** (use the Output directory path above):

1. **Bootstrap**
   ```bash
   cd {out}/infra/bootstrap
   terraform init
   terraform apply -auto-approve
   ```

2. **Update backend config** — Copy bootstrap outputs into `infra/envs/dev/backend.hcl`, `infra/envs/prod/backend.hcl`, and tfvars:
   ```bash
   terraform output -raw tfstate_bucket
   terraform output -raw tflock_table
   terraform output -raw cloudtrail_bucket
   ```

3. **Dev environment**
   ```bash
   cd {out}/infra/envs/dev
   terraform init -backend-config=backend.hcl -reconfigure
   terraform apply -auto-approve -var-file=dev.tfvars
   ```

4. **Prod environment**
   ```bash
   cd {out}/infra/envs/prod
   terraform init -backend-config=backend.hcl -reconfigure
   terraform apply -auto-approve -var-file=prod.tfvars
   ```

5. **Then run this UI again** (or the pipeline) — Build, Deploy (Ansible), and Verify will use the applied infra.

See `RUN_ORDER.md` in the output directory for full details.
"""


def _parse_and_apply_env_vars(text: str) -> dict:
    """
    Parse KEY=value lines (like .env) and set os.environ.
    Returns dict of previous values for keys we set (for restore).
    Skips empty lines, # comments, and empty values (to avoid clearing .env).
    """
    prev = {}
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            val = value.strip()
            if key and val:  # Only set non-empty values; skip to avoid clearing .env
                prev[key] = os.environ.get(key)
                os.environ[key] = val
    return prev


def _resolve_env_path(env_file_path: str, env_file_upload) -> str:
    """Resolve .env path: uploaded file > typed path > default."""
    upload_path = getattr(env_file_upload, "name", env_file_upload) if env_file_upload else None
    if upload_path and os.path.isfile(upload_path):
        return upload_path
    path = (env_file_path or "").strip()
    return path or os.path.join(_THIS_DIR, ".env")


def _restore_env_vars(prev: dict) -> None:
    """Restore env to previous state."""
    for key, val in prev.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def run_combined_crew(
    env_file_path,
    env_file_upload,
    requirements_file,
    requirements_json,
    output_dir,
    app_dir,
    prod_url,
    aws_region,
    deploy_method,
    allow_terraform_apply,
    confirm_no_apply,
    key_name,
    pem_file,
    pem_path,
    env_vars,
):
    """
    Run the Combined-Crew from the UI inputs.
    requirements_file: uploaded file (path string or None).
    requirements_json: raw JSON text (used if no file uploaded).
    pem_file: uploaded PEM file path (when using ssh_script).
    pem_path: text path to PEM (alternative to upload).
    """
    # Load .env from uploaded file, path, or default
    env_path = _resolve_env_path(env_file_path, env_file_upload)
    if load_dotenv and os.path.isfile(env_path):
        load_dotenv(env_path)

    # Apply env vars before checking OPENAI_API_KEY (user may provide it here)
    env_prev = _parse_and_apply_env_vars(env_vars or "")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        _restore_env_vars(env_prev)
        return (
            "Error: OPENAI_API_KEY is required. Set it in your .env file, upload a .env file, "
            "or add OPENAI_API_KEY=sk-... in the Environment variables section."
        )

    # Terraform apply confirmation when disabled
    if not allow_terraform_apply and not confirm_no_apply:
        _restore_env_vars(env_prev)
        return MSG_TERRAFORM_NO_APPLY_CONFIRM

    if not requirements_file and not (requirements_json or "").strip():
        _restore_env_vars(env_prev)
        return "Error: Provide a requirements.json file or paste JSON in the text box."
    try:
        from run import load_requirements, run_crew
        req_path = getattr(requirements_file, "name", requirements_file) if requirements_file else None
        if req_path and os.path.isfile(req_path):
            requirements = load_requirements(req_path)
        else:
            requirements = json.loads(requirements_json.strip())
    except json.JSONDecodeError as e:
        _restore_env_vars(env_prev)
        return f"Invalid JSON: {e}"
    except Exception as e:
        _restore_env_vars(env_prev)
        return f"Failed to load requirements: {e}"

    # Priority: UI value, then OUTPUT_DIR from .env, then default
    output_dir = (output_dir or "").strip() or (os.environ.get("OUTPUT_DIR") or "").strip()
    if not output_dir:
        output_dir = os.path.join(_THIS_DIR, "output")
    app_dir = (app_dir or "").strip() or None
    prod_url = (prod_url or "").strip()
    aws_region = (aws_region or "").strip() or "us-east-1"
    deploy_method = (deploy_method or "ansible").strip().lower()

    ssh_key_path = ""
    ssh_key_content = None
    if deploy_method == "ssh_script":
        pem_path_resolved = getattr(pem_file, "name", pem_file) if pem_file else None
        if pem_path_resolved and os.path.isfile(pem_path_resolved):
            ssh_key_path = pem_path_resolved
        elif (pem_path or "").strip():
            p = pem_path.strip()
            if os.path.isfile(p):
                ssh_key_path = p
            else:
                _restore_env_vars(env_prev)
                return f"PEM key file not found: {p}"

    try:
        success, message = run_crew(
        requirements=requirements,
        output_dir=output_dir,
        prod_url=prod_url,
        aws_region=aws_region,
        deploy_method=deploy_method,
        allow_terraform_apply=bool(allow_terraform_apply),
        key_name=(key_name or "").strip(),
        ssh_key_path=ssh_key_path,
        ssh_key_content=ssh_key_content,
        app_dir=app_dir,
    )
    finally:
        _restore_env_vars(env_prev)
    return message


def run_teardown(env_file_path, env_file_upload, output_dir, aws_region, env_vars):
    """Tear down all infrastructure (terraform destroy)."""
    from destroy import run_destroy
    env_path = _resolve_env_path(env_file_path, env_file_upload)
    if load_dotenv and os.path.isfile(env_path):
        load_dotenv(env_path)
    env_prev = _parse_and_apply_env_vars(env_vars or "")
    try:
        # Use specified output_dir; fall back to OUTPUT_DIR from .env, then default
        out_dir = (output_dir or "").strip() or (os.environ.get("OUTPUT_DIR") or "").strip()
        if not out_dir:
            out_dir = os.path.join(_THIS_DIR, "output")
        region = (aws_region or "").strip() or "us-east-1"
        success, msg = run_destroy(output_dir=out_dir, aws_region=region, confirm=False)
        return msg
    finally:
        _restore_env_vars(env_prev)


def build_ui():
    with gr.Blocks(title="Combined-Crew") as demo:
        gr.Markdown(
            """
            # DevOps-Crew
            Run **Generate → Infra → Build → Deploy → Verify** from requirements.
            Provide `requirements.json` (upload or paste) and configure options below.
            """
        )
        gr.Markdown(
            "**If Terraform fails with VpcLimitExceeded/AddressLimitExceeded:** Run `python Combined-Crew/scripts/resolve-aws-limits.py --release-unassociated-eips` and `remove-terraform-blockers.py` from the project root, then re-run. See RUN_ORDER.md §0 in the output directory."
        )

        with gr.Row():
            with gr.Column(scale=1):
                env_file_path = gr.Textbox(
                    label=".env file path",
                    value=os.path.join(_THIS_DIR, ".env"),
                    placeholder="C:/path/to/.env",
                )
                env_file_upload = gr.File(
                    label="Or upload .env file",
                    type="filepath",
                )
                gr.DownloadButton(
                    label="Download sample requirements.json",
                    value=os.path.join(_THIS_DIR, "sample_requirements.json"),
                    variant="secondary",
                )
                requirements_file = gr.File(
                    file_types=[".json"],
                    label="Upload requirements.json",
                    type="filepath",
                )
                requirements_json = gr.Textbox(
                    label="Or paste JSON here (used if no file uploaded)",
                    placeholder='{"project":"myapp","region":"us-east-1","dev":{...},"prod":{...}}',
                    lines=8,
                )
                output_dir = gr.Textbox(
                    label="Output directory (where the project will be generated)",
                    value=os.environ.get("OUTPUT_DIR", "").strip() or os.path.join(_THIS_DIR, "output"),
                    placeholder="./output",
                )
                app_dir = gr.Textbox(
                    label="Application directory (optional: folder with app to deploy; leave blank to use generated app)",
                    placeholder="C:/path/to/your-app",
                )
                prod_url = gr.Textbox(
                    label="Production URL (optional; verifier prefers Terraform https_url; use domain from requirements, e.g. https://app.my-iifb.click, no www)",
                    value=os.environ.get("PROD_URL", "").strip(),
                    placeholder="https://app.example.com",
                )
                aws_region = gr.Textbox(
                    label="AWS region",
                    value="us-east-1",
                    placeholder="us-east-1",
                )
                _dm = (os.environ.get("DEPLOY_METHOD") or "ansible").strip().lower()
                _dm = _dm if _dm in ("ansible", "ssh_script", "ecs") else "ansible"
                deploy_method = gr.Radio(
                    choices=["ansible", "ssh_script", "ecs"],
                    value=_dm,
                    label="Deploy method (ansible | ssh_script | ecs)",
                )
                _allow_init = False if _dm == "ansible" else (os.environ.get("ALLOW_TERRAFORM_APPLY", "").strip() == "1")
                allow_terraform_apply = gr.Checkbox(
                    label="Allow Terraform apply (unchecked = plan only)",
                    value=_allow_init,
                    interactive=(_dm != "ansible"),
                )
                with gr.Group(visible=True) as terraform_confirm_group:
                    confirm_no_apply = gr.Checkbox(
                        label="I confirm: run without Terraform apply (plan only)",
                        value=False,
                    )

                allow_terraform_apply.change(
                    toggle_terraform_confirm,
                    inputs=[allow_terraform_apply],
                    outputs=[terraform_confirm_group],
                )

                with gr.Accordion("Environment variables (optional)", open=False):
                    gr.Markdown(
                        "Override or supplement the .env file. KEY=value per line. These take precedence over the .env file for this run."
                    )
                    env_vars = gr.Textbox(
                        label="Variables (required and optional listed below)",
                        value=ENV_TEMPLATE,
                        lines=28,
                    )

                with gr.Group(visible=(_dm == "ssh_script")) as ssh_group:
                    gr.Markdown("**SSH options** (for deploy method: ssh_script)")
                    pem_path = gr.Textbox(
                        label="Path to PEM key file",
                        placeholder="C:/path/to/your-key.pem",
                    )
                    pem_file = gr.File(
                        file_types=[".pem"],
                        label="Or upload PEM key (alternative to path above)",
                        type="filepath",
                    )
                    key_name = gr.Textbox(
                        label="AWS key pair name (must match EC2 launch key)",
                        value=os.environ.get("KEY_NAME", ""),
                        placeholder="e.g. my-ec2-key",
                    )

                with gr.Group(visible=(_dm == "ansible")) as ansible_procedure_group:
                    gr.Markdown("**Ansible: run Terraform apply manually** (Terraform apply is disabled)")
                    _out_init = os.environ.get("OUTPUT_DIR", "").strip() or os.path.join(_THIS_DIR, "output")
                    ansible_procedure_md = gr.Markdown(
                        value=_ansible_procedure_md(_out_init),
                        elem_classes=["ansible-procedure"],
                    )

                deploy_method.change(
                    toggle_ssh_fields,
                    inputs=[deploy_method],
                    outputs=[ssh_group],
                )
                deploy_method.change(
                    toggle_deploy_method_ansible,
                    inputs=[deploy_method, output_dir],
                    outputs=[allow_terraform_apply, ansible_procedure_group, ansible_procedure_md],
                )
                output_dir.change(
                    lambda o: _ansible_procedure_md(o or ""),
                    inputs=[output_dir],
                    outputs=[ansible_procedure_md],
                )

            with gr.Column(scale=1):
                run_btn = gr.Button("Run Combined-Crew", variant="primary", size="lg")
                gr.Markdown("*Tear down: runs `terraform destroy` on the output directory (prod → dev → bootstrap).*")
                teardown_btn = gr.Button("Tear down infrastructure", variant="stop", size="lg")
                output = gr.Textbox(
                    label="Output",
                    lines=20,
                    max_lines=30,
                    elem_classes=["output-box"],
                )

        run_btn.click(
            fn=run_combined_crew,
            inputs=[
                env_file_path,
                env_file_upload,
                requirements_file,
                requirements_json,
                output_dir,
                app_dir,
                prod_url,
                aws_region,
                deploy_method,
                allow_terraform_apply,
                confirm_no_apply,
                key_name,
                pem_file,
                pem_path,
                env_vars,
            ],
            outputs=[output],
        )

        teardown_btn.click(
            fn=run_teardown,
            inputs=[env_file_path, env_file_upload, output_dir, aws_region, env_vars],
            outputs=[output],
        )

        gr.Markdown(
            """
            ---
            **Note:** Use the **.env file path** to load variables from a file, or set them in the **Environment variables** section. Required: `OPENAI_API_KEY`. For AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
            """
        )

    return demo


def main():
    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(),
        css=""" .output-box { font-family: monospace; white-space: pre-wrap; } """,
    )


if __name__ == "__main__":
    main()
