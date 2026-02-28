#!/usr/bin/env bash
set -euo pipefail
REGION=$(aws configure get region || echo us-east-1)
IMAGE_TAG=$(aws ssm get-parameter --name "/bluegreen/prod/image_tag" --query "Parameter.Value" --output text 2>/dev/null || echo "latest")
ECR_REPO=$(aws ssm get-parameter --name "/bluegreen/prod/ecr_repo_name" --query "Parameter.Value" --output text 2>/dev/null || echo "bluegreen-prod-app")
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker pull ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
docker run -d --name bluegreen-app -p 8080:8080 --restart unless-stopped ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
