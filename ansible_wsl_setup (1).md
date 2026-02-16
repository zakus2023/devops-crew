# Run Ansible on Windows (Correctly) using WSL — Step‑by‑Step

This guide fixes both issues you hit on Windows:
- **`ansible: command not found`** (Ansible installed in a venv but not visible in the current shell)
- **`WinError 1 Incorrect function`** (Ansible CLI incompatibility on native Windows / Git Bash)

✅ The reliable solution is: **run Ansible inside WSL (Linux)** and access your Windows repo via `/mnt/c/...`.

---

## 0) Prereqs (one-time)
- Windows 10 (version 2004+) or Windows 11
- Administrator access (for installing WSL and Ubuntu the first time)

---

## 0a) Install WSL and Ubuntu

If you don’t have WSL or Ubuntu yet, do this once from **PowerShell (Run as administrator)**.

### Enable WSL and install Ubuntu in one step (recommended)

```powershell
wsl --install -d Ubuntu
```

- This enables the **WSL 2** feature and installs **Ubuntu** from the Microsoft Store.
- When it finishes, it may ask you to **restart** your PC. Restart, then continue below.

### If `wsl --install` is not available (older Windows)

1. Enable WSL (PowerShell as Administrator):
   ```powershell
   dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```
2. Restart the PC.
3. Install **Ubuntu** from the Microsoft Store: open **Microsoft Store**, search for **Ubuntu**, and click **Get** / **Install**.

### First run of Ubuntu

1. Open **Ubuntu** from the Start menu (or run `wsl -d Ubuntu` in PowerShell).
2. Wait for it to finish installing (one-time setup).
3. When prompted, create a **Linux username** and **password**. This user is separate from your Windows login; you’ll use it for `sudo` inside WSL.

If you see:
> `ERROR_ALREADY_EXISTS`

when running `wsl --install -d Ubuntu`, Ubuntu is already installed — go to section 1.

---

## 1) Confirm WSL and your installed distros (PowerShell)
Open **PowerShell** (normal user is fine) and run:

```powershell
wsl -l -v
```

You should see something like:

```
  NAME            STATE           VERSION
* Ubuntu          Stopped         2
```

### If Ubuntu exists
Run:
```powershell
wsl -d Ubuntu
```

### If you’re not sure which distro to use
You can just run:
```powershell
wsl
```
It opens your default distro.

---

## 2) Update Linux packages (inside WSL)
Once you’re inside WSL (you’ll see a Linux prompt like `user@machine:~$`):

```bash
sudo apt update
sudo apt -y upgrade
```

---

## 3) Install Ansible + Python tooling (inside WSL)
```bash
sudo apt install -y ansible python3-pip python3-venv
```

Verify:
```bash
ansible --version
ansible-galaxy --version
python3 --version
pip3 --version
```

---

## 4) Access your Windows project folder from WSL
Your Windows **C:** drive is mounted at `/mnt/c`.

For your repo:
```bash
cd /mnt/c/My-Projects/crew-DevOps/Multi-Agent-Pipeline
```

Verify you are in the right place:
```bash
ls
```

---

## 5) Create and activate a virtual environment (venv) in Ubuntu

A **venv** is an isolated Python environment for a project. It keeps dependencies (e.g. `boto3`) separate from the system Python and avoids conflicts. You **can** use system Ansible without a venv; the venv is mainly for extra Python libs like `boto3`.

### 5.1 Create the venv (one-time per project)

From your project directory inside WSL (e.g. the repo root or the folder where you want the venv):

```bash
cd /mnt/c/My-Projects/crew-DevOps/Multi-Agent-Pipeline
python3 -m venv .venv-linux
```

- `.venv-linux` is the folder name of the venv (you can use another name, e.g. `.venv`).
- This creates the folder and a copy of the Python interpreter and pip inside it.

### 5.2 Activate the venv

**You must activate the venv in every new WSL terminal** where you want to use that environment:

```bash
source .venv-linux/bin/activate
```

After activation, your prompt usually shows the venv name in parentheses, e.g.:

```
(.venv-linux) user@machine:/mnt/c/My-Projects/crew-DevOps/Multi-Agent-Pipeline$
```

- Commands like `pip` and `python` now use the venv’s Python and packages.
- `ansible` and `ansible-playbook` are still the system ones (from `apt`) unless you install Ansible inside the venv; the venv is mainly for libs like `boto3`.

### 5.3 Deactivate the venv

To leave the venv and use system Python again:

```bash
deactivate
```

### 5.4 Upgrade pip inside the venv (recommended)

After activating:

```bash
python -m pip install --upgrade pip
```

---

## 6) Install AWS dependencies required by `amazon.aws` / `community.aws` (inside WSL)

If you created the venv in section 5, activate it first: `source .venv-linux/bin/activate`.

### 6.1 Install Ansible collections
```bash
ansible-galaxy collection install amazon.aws community.aws
```

### 6.2 Install Python AWS SDK libs (in active venv or system)
```bash
pip install boto3 botocore
```

---

## 7) Configure AWS credentials for Ansible (inside WSL)
You need AWS creds for dynamic inventory and AWS modules.

### Option A (recommended): `aws configure` (requires AWS CLI)
Install AWS CLI:
```bash
sudo apt install -y awscli
```

Configure:
```bash
aws configure
```

Confirm:
```bash
aws sts get-caller-identity
```

### Option B: environment variables (quick test)
```bash
export AWS_ACCESS_KEY_ID="YOUR_KEY"
export AWS_SECRET_ACCESS_KEY="YOUR_SECRET"
export AWS_DEFAULT_REGION="us-east-1"
aws sts get-caller-identity
```

---

## 8) Test your AWS dynamic inventory file (inside WSL)
From your repo root, run:

```bash
ansible-inventory -i inventory/ec2_dev.yml --graph
```

Or list hosts:
```bash
ansible-inventory -i inventory/ec2_dev.yml --list
```

If you see your EC2 instances, inventory works.

---

## 9) Run a playbook (inside WSL)
Example:
```bash
ansible-playbook -i inventory/ec2_dev.yml playbooks/dev.yml
```

If you have separate prod:
```bash
ansible-playbook -i inventory/ec2_prod.yml playbooks/prod.yml
```

---

## 10) SSH considerations (important)
For Ansible to SSH into instances, you must have:
- Correct security group rules (allow SSH from your IP)
- Key-based auth configured
- Correct user (e.g., `ubuntu`, `ec2-user`)

### Example: pass SSH user + key
```bash
ansible-playbook -i inventory/ec2_dev.yml playbooks/dev.yml \
  -u ubuntu --private-key ~/.ssh/your-key.pem
```

### If your inventory sets the user
You can set:
- `ansible_user`
- `ansible_ssh_private_key_file`

in `group_vars/` or inventory vars.

---

## 11) Why your Windows venv failed (for reference)
On native Windows / Git Bash / MinGW you can hit:

- `ansible-playbook: command not found`  
  → venv not activated or PATH not pointing to `.venv\\Scripts`

- `OSError: [WinError 1] Incorrect function`  
  → Ansible CLI uses POSIX-like file descriptor behavior. Git Bash/MinGW descriptors often break `os.get_blocking()`.
  → **This is not reliably fixable on Windows**.

✅ WSL avoids both by running Ansible in a real Linux environment.

---

## 12) Quick troubleshooting checklist

### 12.1 “WSL opens, but my repo path doesn’t exist”
Confirm the Windows path:
```bash
ls /mnt/c/My-Projects/crew-DevOps/
```

### 12.2 “Ansible inventory shows empty hosts”
- Confirm EC2 tags match your filters (`tag:Env: dev` etc.)
- Confirm region is correct in inventory file
- Confirm AWS creds are valid:
```bash
aws sts get-caller-identity
```

### 12.3 “SSH unreachable”
- Check instance public IP / DNS
- Confirm SG allows inbound 22 from your IP
- Confirm correct SSH user and key

### 12.4 “collection not found / module not found”
Reinstall:
```bash
ansible-galaxy collection install amazon.aws community.aws --force
```

---

## 13) Optional: make Ubuntu the default WSL distro (PowerShell)
If you want `wsl` to always open Ubuntu:

```powershell
wsl -s Ubuntu
```

---

## 14) Optional alternative: run Ansible in Docker (no WSL)
If you prefer Docker over WSL, run from Windows repo root:

```powershell
docker run --rm -it -v ${PWD}:/work -w /work quay.io/ansible/ansible-runner:stable ansible --version
```

Install collections:
```powershell
docker run --rm -it -v ${PWD}:/work -w /work quay.io/ansible/ansible-runner:stable ansible-galaxy collection install community.aws
```

Run playbook:
```powershell
docker run --rm -it -v ${PWD}:/work -w /work quay.io/ansible/ansible-runner:stable ansible-playbook -i inventory/ec2_dev.yml playbooks/dev.yml
```

---

## Done ✅
If you paste your `wsl -l -v` output + your `inventory/ec2_dev.yml`, I can add a “known-good” AWS inventory test command and recommended vars for your exact layout.

---

## 15) Uninstalling Ansible (WSL Ubuntu 24.04 - PEP 668 aware)

Ubuntu installs Ansible via `apt`, not `pip`.  
Because of **PEP 668 (externally-managed-environment)** you cannot remove it with `pip uninstall`.

### Remove completely
```bash
sudo apt remove -y ansible ansible-core
sudo apt autoremove -y
```

Verify removal:
```bash
ansible --version
```

You should see: `command not found`

### Why `pip uninstall ansible` failed
Ubuntu protects system Python packages. If installed using `apt`, only `apt` can remove it.

### Recommended setup (best practice)
Keep Ansible installed system-wide, install AWS SDKs in project venv:

```bash
cd /mnt/c/My-Projects/crew-DevOps/Multi-Agent-Pipeline
python3 -m venv .venv-linux
source .venv-linux/bin/activate
pip install boto3 botocore
```

Do NOT run:
```bash
pip install ansible
```
inside WSL — it causes dependency conflicts and breaks system tooling.
