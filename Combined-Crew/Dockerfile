# DevOps-Crew Space: Python + Terraform + Docker + Gradio
# Enables full pipeline (Generate → Infra → Build → Deploy → Verify) including Terraform apply.
# Build step requires Docker: run with -v /var/run/docker.sock:/var/run/docker.sock for local use.
# HF Spaces typically do not expose Docker socket — Build will fail there; run pipeline locally for full flow.
FROM python:3.11-slim

# Install Terraform (required for Infra step)
ENV TERRAFORM_VERSION=1.9.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && curl -fsSL -o /tmp/terraform.zip \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm /tmp/terraform.zip \
    && terraform --version \
    && apt-get purge -y curl unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (required for Build step; needs Docker socket: -v /var/run/docker.sock:/var/run/docker.sock)
# Install OpenSSH client for DEPLOY_METHOD=ssh_script (run_ssh_deploy uses ssh binary)
RUN apt-get update && apt-get install -y --no-install-recommends docker.io openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create user (HF Spaces run as uid 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# Python dependencies (awscli for Teardown step: empty S3 buckets, delete ECR)
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt awscli

# App entry point (downloads project from model repo at runtime)
COPY --chown=user app.py .

EXPOSE 7860
CMD ["python", "app.py"]
