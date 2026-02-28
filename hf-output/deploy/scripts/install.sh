#!/usr/bin/env bash
set -euo pipefail
systemctl enable docker || true
systemctl start docker || true
mkdir -p /opt/codedeploy-bluegreen
