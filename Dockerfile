# DevOps-Crew: Render deployment (full project from Git)
# Pipeline: Generate → Infra → Build → Deploy → Verify
# Build step: Render containers lack Docker socket — use CodeBuild or PRE_BUILT_IMAGE_TAG / ecr_list_image_tags
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

# Docker CLI (Build step uses CodeBuild/ecr fallback when socket unavailable)
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy full project (required for run.py, flow.py, agents)
COPY Combined-Crew/ ./Combined-Crew/
COPY Full-Orchestrator/ ./Full-Orchestrator/
COPY Multi-Agent-Pipeline/ ./Multi-Agent-Pipeline/
COPY infra/ ./infra/

# Python deps + awscli
RUN pip install --no-cache-dir -r Combined-Crew/requirements.txt awscli

WORKDIR /app/Combined-Crew
EXPOSE 7860
CMD ["python", "app.py"]
