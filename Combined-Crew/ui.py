#!/usr/bin/env python3
"""
Gradio UI for Combined-Crew: run Generate → Infra → Build → Deploy → Verify from a web interface.

Usage:
  python ui.py
  # Or: gradio ui.py

Then open the URL shown (default http://127.0.0.1:7860).
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile


class _StreamCapturer:
    """Captures stdout/stderr to a buffer for live UI display. Thread-safe."""

    def __init__(self, original, label=""):
        self._original = original
        self._label = label
        self._buffer = io.StringIO()
        self._lock = threading.Lock()

    def write(self, text):
        if text:
            with self._lock:
                self._buffer.write(text)
            try:
                self._original.write(text)
            except Exception:
                pass

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self):
        return False  # Web UI, not a real terminal (CrewAI/Rich check this)

    def getvalue(self):
        with self._lock:
            return self._buffer.getvalue()

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
# DEPLOY_METHOD=ssh_script
# DEPLOY_METHOD=ansible
# DEPLOY_METHOD=ecs
# APP_ROOT=
# PRE_BUILT_IMAGE_TAG=abc123  # When Docker unavailable (HF Space): tag from GitHub Actions or ecr_list_image_tags

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
        gr.update(value=not is_ansible, interactive=not is_ansible),  # allow_terraform_apply: True for ssh_script/ecs
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


def _zip_output_for_download(output_dir: str) -> str | None:
    """
    Zip the output directory for download. Excludes large dirs (.terraform, node_modules).
    Returns path to the zip file, or None if output_dir is invalid.
    """
    if not output_dir or not os.path.isdir(output_dir):
        return None
    exclude_dirs = {".terraform", "node_modules", "__pycache__"}
    try:
        fd, zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(output_dir):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                rel_root = os.path.relpath(root, output_dir)
                if rel_root == ".":
                    rel_root = ""
                for f in files:
                    path = os.path.join(root, f)
                    arcname = os.path.join(rel_root, f) if rel_root else f
                    zf.write(path, arcname)
        return zip_path
    except Exception:
        return None


def _delete_output(output_dir: str) -> str:
    """
    Delete the output directory from the filesystem (e.g. on Hugging Face Space).
    Returns a status message. Only deletes paths under the project or cwd.
    """
    out = (output_dir or "").strip() or os.path.join(_THIS_DIR, "output")
    if not os.path.isabs(out):
        out = os.path.abspath(out)
    if not os.path.isdir(out):
        return f"Output directory does not exist or is not a directory: {out}"
    real_out = os.path.realpath(out)
    real_this = os.path.realpath(_THIS_DIR)
    real_cwd = os.path.realpath(os.getcwd())
    # Safety: only delete if under project dir or cwd
    if not (
        real_out == real_this
        or real_out.startswith(real_this + os.sep)
        or real_out == real_cwd
        or real_out.startswith(real_cwd + os.sep)
    ):
        return f"Refusing to delete: path is outside the project directory."
    try:
        shutil.rmtree(out)
        return f"Deleted output directory: {out}"
    except Exception as e:
        return f"Failed to delete: {e}"


def _is_valid_http_url(s: str) -> bool:
    """True if s looks like an HTTP/HTTPS URL (not a file path)."""
    s = (s or "").strip()
    if not s:
        return False
    # Windows path (C:\, D:\) or Unix path starting with /
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        return False
    if s.startswith("/") or s.startswith("."):
        return False
    return s.startswith("http://") or s.startswith("https://")


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
            val = value.strip().strip('"').strip("'")  # Remove surrounding quotes
            if key and val:
                prev[key] = os.environ.get(key)
                os.environ[key] = val
    return prev


def _find_app_in_extracted(extract_dir: str) -> str:
    """Find folder containing Dockerfile, app.py, or server.js (handles flat and nested structure)."""
    def has_app_files(d: str) -> bool:
        return (
            os.path.isfile(os.path.join(d, "Dockerfile"))
            or os.path.isfile(os.path.join(d, "app.py"))
            or os.path.isfile(os.path.join(d, "server.js"))
        )
    if has_app_files(extract_dir):
        return extract_dir
    for name in os.listdir(extract_dir):
        sub = os.path.join(extract_dir, name)
        if os.path.isdir(sub) and has_app_files(sub):
            return sub
    return extract_dir


def _find_output_root(extract_dir: str) -> str:
    """Find the output root (dir containing infra/) in extracted zip. Handles nested structure."""
    if os.path.isdir(os.path.join(extract_dir, "infra")):
        return extract_dir
    for name in os.listdir(extract_dir):
        sub = os.path.join(extract_dir, name)
        if os.path.isdir(sub) and os.path.isdir(os.path.join(sub, "infra")):
            return sub
    return extract_dir


def _resolve_output_dir(output_dir: str) -> str:
    """Resolve output_dir to absolute path. On HF Space, relative paths like ./output resolve relative to Combined-Crew."""
    out = (output_dir or "").strip() or os.path.join(_THIS_DIR, "output")
    if os.name != "nt" and len(out) >= 2 and out[1] == ":" and out[0].isalpha():
        out = os.path.join(_THIS_DIR, "output")
    if not os.path.isabs(out):
        out = os.path.normpath(os.path.join(_THIS_DIR, out))
    return os.path.abspath(out)


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
    app_dir_upload,
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
        yield (
            "Error: OPENAI_API_KEY is required. Set it in your .env file, upload a .env file, "
            "or add OPENAI_API_KEY=sk-... in the Environment variables section."
        ), None
        return

    # Terraform apply confirmation when disabled
    if not allow_terraform_apply and not confirm_no_apply:
        _restore_env_vars(env_prev)
        yield MSG_TERRAFORM_NO_APPLY_CONFIRM, None
        return

    if not requirements_file and not (requirements_json or "").strip():
        _restore_env_vars(env_prev)
        yield "Error: Provide a requirements.json file or paste JSON in the text box.", None
        return
    try:
        from run import load_requirements
        req_path = getattr(requirements_file, "name", requirements_file) if requirements_file else None
        if req_path and os.path.isfile(req_path):
            requirements = load_requirements(req_path)
        else:
            requirements = json.loads(requirements_json.strip())
    except json.JSONDecodeError as e:
        _restore_env_vars(env_prev)
        yield f"Invalid JSON: {e}", None
        return
    except Exception as e:
        _restore_env_vars(env_prev)
        yield f"Failed to load requirements: {e}", None
        return

    # Priority: UI value, then OUTPUT_DIR from .env, then default
    output_dir = (output_dir or "").strip() or (os.environ.get("OUTPUT_DIR") or "").strip()
    if not output_dir:
        output_dir = os.path.join(_THIS_DIR, "output")
    # On Linux (e.g. HF Space), Windows paths like C:\... are invalid - use fallback
    if os.name != "nt" and len(output_dir) >= 2 and output_dir[1] == ":" and output_dir[0].isalpha():
        output_dir = os.path.join(_THIS_DIR, "output")
    # App dir: upload (zip) takes precedence over path
    app_dir = (app_dir or "").strip() or None
    app_extract_dir = None
    if app_dir_upload:
        upload_path = getattr(app_dir_upload, "name", app_dir_upload) if app_dir_upload else None
        if upload_path and os.path.isfile(upload_path) and upload_path.lower().endswith(".zip"):
            app_extract_dir = tempfile.mkdtemp(prefix="app_upload_")
            try:
                with zipfile.ZipFile(upload_path, "r") as zf:
                    zf.extractall(app_extract_dir)
                app_dir = _find_app_in_extracted(app_extract_dir)
                if not os.path.isfile(os.path.join(app_dir, "Dockerfile")):
                    if app_extract_dir and os.path.isdir(app_extract_dir):
                        try:
                            shutil.rmtree(app_extract_dir, ignore_errors=True)
                        except Exception:
                            pass
                    _restore_env_vars(env_prev)
                    yield "App folder must contain a Dockerfile for build. Upload a zip with Dockerfile.", None
                    return
            except Exception as e:
                if app_extract_dir and os.path.isdir(app_extract_dir):
                    try:
                        shutil.rmtree(app_extract_dir, ignore_errors=True)
                    except Exception:
                        pass
                _restore_env_vars(env_prev)
                yield f"Failed to extract app zip: {e}", None
                return
    # Validate app_dir has Dockerfile when provided (path or from upload)
    if app_dir and os.path.isdir(app_dir) and not os.path.isfile(os.path.join(app_dir, "Dockerfile")):
        if app_extract_dir and os.path.isdir(app_extract_dir):
            try:
                shutil.rmtree(app_extract_dir, ignore_errors=True)
            except Exception:
                pass
        _restore_env_vars(env_prev)
        yield "App directory must contain a Dockerfile for build.", None
        return
    # Reject swapped fields: prod_url must be HTTP(S) URL; app_dir must not be a URL
    prod_url = (prod_url or "").strip()
    if prod_url and not _is_valid_http_url(prod_url):
        prod_url = ""  # File path in Production URL field — treat as unset
    if app_dir and (app_dir.startswith("http://") or app_dir.startswith("https://")):
        app_dir = None  # URL in Application directory — likely swapped
    aws_region = (aws_region or "").strip() or "us-east-1"
    # Priority: UI input (deploy method radio) first, then DEPLOY_METHOD from .env
    deploy_method = (deploy_method or os.environ.get("DEPLOY_METHOD") or "ansible").strip().lower()
    # Normalize invalid deploy methods (ecs_script->ecs; shs_script->ssh_script; codedeploy->ssh_script)
    if deploy_method == "ecs_script":
        deploy_method = "ecs"
    elif deploy_method == "shs_script" or deploy_method == "codedeploy":
        deploy_method = "ssh_script"
    elif deploy_method not in ("ansible", "ssh_script", "ecs"):
        deploy_method = "ansible"

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
                yield f"PEM key file not found: {p}", None
                return

    # Run pipeline in subprocess — when it exits, OS reclaims memory (free tier 512MB)
    job_data = {
        "requirements": requirements,
        "output_dir": output_dir,
        "prod_url": prod_url,
        "aws_region": aws_region,
        "deploy_method": deploy_method,
        "allow_terraform_apply": bool(allow_terraform_apply),
        "key_name": (key_name or "").strip(),
        "ssh_key_path": ssh_key_path,
        "app_dir": app_dir,
    }
    fd, job_path = tempfile.mkstemp(suffix=".json", prefix="run_job_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job_data, f, indent=2)
    except Exception as e:
        try:
            os.close(fd)
        except OSError:
            pass
        _restore_env_vars(env_prev)
        yield f"Failed to write job file: {e}", None
        return

    env = os.environ.copy()
    if ssh_key_content:
        env["SSH_PRIVATE_KEY"] = ssh_key_content

    run_cli = os.path.join(_THIS_DIR, "run_cli.py")
    proc = subprocess.Popen(
        [sys.executable, run_cli, job_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=_THIS_DIR,
        bufsize=1,
    )

    output_chunks = []
    done = threading.Event()

    def _read_stdout():
        try:
            if proc.stdout:
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        output_chunks.append(line)
        except Exception:
            pass
        done.set()

    reader = threading.Thread(target=_read_stdout)
    reader.start()

    yield ("Starting pipeline (subprocess)... (live output will stream below)\n", None)

    last_len = 0
    while not done.is_set() or reader.is_alive():
        time.sleep(2)
        out = "".join(output_chunks)
        if out and len(out) != last_len:
            yield (out, None)
            last_len = len(out)
        if proc.poll() is not None and not reader.is_alive():
            break

    # Drain any remaining output
    out = "".join(output_chunks)
    exit_code = proc.returncode
    success = exit_code == 0
    resolved_dir = os.path.abspath(output_dir) if success and output_dir else None
    yield (out, resolved_dir)

    # Cleanup
    _restore_env_vars(env_prev)
    try:
        os.remove(job_path)
    except OSError:
        pass
    if app_extract_dir and os.path.isdir(app_extract_dir):
        try:
            shutil.rmtree(app_extract_dir, ignore_errors=True)
        except Exception:
            pass


def run_teardown(env_file_path, env_file_upload, output_dir, output_upload, aws_region, env_vars):
    """Tear down all infrastructure (terraform destroy). Uses output_dir or extracts output_upload (zip)."""
    from destroy import run_destroy
    env_path = _resolve_env_path(env_file_path, env_file_upload)
    if load_dotenv and os.path.isfile(env_path):
        load_dotenv(env_path)
    env_prev = _parse_and_apply_env_vars(env_vars or "")
    extract_dir = None
    try:
        if output_upload:
            upload_path = getattr(output_upload, "name", output_upload) if output_upload else None
            if upload_path and os.path.isfile(upload_path) and str(upload_path).lower().endswith(".zip"):
                extract_dir = tempfile.mkdtemp(prefix="teardown_output_")
                try:
                    with zipfile.ZipFile(upload_path, "r") as zf:
                        zf.extractall(extract_dir)
                    out_dir = _find_output_root(extract_dir)
                    if not os.path.isdir(os.path.join(out_dir, "infra", "bootstrap")):
                        return f"Invalid output zip: no infra/bootstrap found. Ensure you upload the zip from Download output."
                except Exception as e:
                    return f"Failed to extract output zip: {e}"
            else:
                out_dir = _resolve_output_dir(output_dir or "")
        else:
            out_dir = _resolve_output_dir(output_dir or "")
        region = (aws_region or "").strip() or "us-east-1"
        success, msg = run_destroy(
            output_dir=out_dir,
            aws_region=region,
            confirm=False,
            continue_on_error=True,
        )
        return msg
    except Exception as e:
        import traceback
        return f"Teardown error: {e}\n\n{traceback.format_exc()}"
    finally:
        _restore_env_vars(env_prev)
        if extract_dir and os.path.isdir(extract_dir):
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass


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
            "**Full run takes 15–20 min.** Keep this tab open. Free Spaces may timeout; upgrade hardware (Settings → Space hardware) if runs are cut off."
        )
        gr.Markdown(
            "**If Terraform fails with VpcLimitExceeded/AddressLimitExceeded:** Run `python Combined-Crew/scripts/resolve-aws-limits.py --release-unassociated-eips` and `remove-terraform-blockers.py` from the project root, then re-run. See RUN_ORDER.md §0 in the output directory."
        )

        with gr.Row():
            with gr.Column(scale=1):
                env_file_path = gr.Textbox(
                    label=".env file path",
                    value=os.path.join(_THIS_DIR, ".env"),
                    placeholder="/path/to/.env",
                    info="HF Space: use path like .../snapshots/.../Combined-Crew/.env",
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
                    info='Example: {"project":"myapp","region":"us-east-1","dev":{"vpc_cidr":"10.0.0.0/16"},"prod":{"vpc_cidr":"10.1.0.0/16"}}',
                    lines=8,
                )
                _out_default = os.environ.get("OUTPUT_DIR", "").strip() or os.path.join(_THIS_DIR, "output")
                # On HF Space (Linux), use ./output to avoid users pasting Windows paths
                if os.name != "nt" and "/huggingface" in _out_default and "hub" in _out_default:
                    _out_default = "./output"
                output_dir = gr.Textbox(
                    label="Output directory (where the project will be generated)",
                    value=_out_default,
                    placeholder="./output",
                    info="HF Space: use ./output or leave default. Avoid Windows paths (C:\\...) on Linux.",
                )
                output_upload = gr.File(
                    label="Or upload output (zip) for teardown — use when output was deleted (e.g. after HF Space restart)",
                    type="filepath",
                    file_types=[".zip"],
                )
                app_dir = gr.Textbox(
                    label="Application directory (optional)",
                    placeholder="/path/to/your-app",
                    info="Path or upload zip below. Leave blank to use generated app.",
                )
                app_dir_upload = gr.File(
                    label="Or upload app folder (zip) — folder with app.py, Dockerfile, etc.",
                    type="filepath",
                    file_types=[".zip"],
                )
                prod_url = gr.Textbox(
                    label="Production URL (optional)",
                    value=os.environ.get("PROD_URL", "").strip(),
                    placeholder="https://app.yourdomain.com",
                    info="Verifier uses Terraform https_url. Use domain from requirements, no www.",
                )
                aws_region = gr.Textbox(
                    label="AWS region",
                    value="us-east-1",
                    placeholder="us-east-1",
                    info="e.g. us-east-1, us-west-2",
                )
                _dm = (os.environ.get("DEPLOY_METHOD") or "ansible").strip().lower()
                # Normalize invalid values (ecs_script->ecs; shs_script->ssh_script; codedeploy->ssh_script)
                if _dm == "ecs_script":
                    _dm = "ecs"
                elif _dm == "shs_script" or _dm == "codedeploy":
                    _dm = "ssh_script"
                elif _dm not in ("ansible", "ssh_script", "ecs"):
                    _dm = "ansible"
                deploy_method = gr.Radio(
                    choices=["ansible", "ssh_script", "ecs"],
                    value=_dm,
                    label="Deploy method (ansible | ssh_script | ecs)",
                )
                _allow_init = False if _dm == "ansible" else True  # Auto-allow Terraform apply for ssh_script/ecs
                allow_terraform_apply = gr.Checkbox(
                    label="Allow Terraform apply (unchecked = plan only; Build/Deploy/Verify will fail without infra)",
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

                with gr.Accordion("Environment variables (required: OPENAI_API_KEY)", open=True):
                    gr.Markdown(
                        "Provide your own credentials. KEY=value per line. Required: OPENAI_API_KEY. For AWS (Terraform, ECR, deploy): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY. On Render/Hugging Face, use this section — do not share keys in dashboard."
                    )
                    env_vars = gr.Textbox(
                        label="Variables",
                        value=ENV_TEMPLATE,
                        placeholder="OPENAI_API_KEY=sk-...\nAWS_ACCESS_KEY_ID=...\nAWS_SECRET_ACCESS_KEY=...",
                        info="Required: OPENAI_API_KEY. For AWS: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY.",
                        lines=28,
                    )

                with gr.Group(visible=(_dm == "ssh_script")) as ssh_group:
                    gr.Markdown("**SSH options** (for deploy method: ssh_script)")
                    pem_path = gr.Textbox(
                        label="Path to PEM key file",
                        placeholder="/path/to/key.pem",
                        info="Or upload PEM file below.",
                    )
                    pem_file = gr.File(
                        file_types=[".pem"],
                        label="Or upload PEM key (alternative to path above)",
                        type="filepath",
                    )
                    key_name = gr.Textbox(
                        label="AWS key pair name",
                        value=os.environ.get("KEY_NAME", ""),
                        placeholder="my-ec2-keypair",
                        info="Must match EC2 launch key.",
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
                last_output_dir = gr.State(value=None)
                gr.Markdown("*After a successful run, download the output as a zip or delete it from the Space.*")
                with gr.Row():
                    download_btn = gr.DownloadButton("Download output")
                    delete_output_btn = gr.Button("Delete output", variant="secondary")

        run_btn.click(
            fn=run_combined_crew,
            inputs=[
                env_file_path,
                env_file_upload,
                requirements_file,
                requirements_json,
                output_dir,
                app_dir,
                app_dir_upload,
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
            outputs=[output, last_output_dir],
        )

        def _create_download(last_dir):
            path = _zip_output_for_download(last_dir) if last_dir else None
            return path if path else None

        download_btn.click(
            fn=_create_download,
            inputs=[last_output_dir],
            outputs=[download_btn],
        )

        teardown_btn.click(
            fn=run_teardown,
            inputs=[env_file_path, env_file_upload, output_dir, output_upload, aws_region, env_vars],
            outputs=[output],
        )

        def _delete_and_report(output_dir_val):
            msg = _delete_output(output_dir_val)
            return msg, None  # Clear last_output_dir so Download doesn't use stale path

        delete_output_btn.click(
            fn=_delete_and_report,
            inputs=[output_dir],
            outputs=[output, last_output_dir],
        )

        gr.Markdown(
            """
            ---
            **Note:** Use the **.env file path** to load variables from a file, or set them in the **Environment variables** section. Required: `OPENAI_API_KEY`. For AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
            """
        )

    demo.queue(default_concurrency_limit=1)  # One run at a time; streaming keeps connection alive
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
