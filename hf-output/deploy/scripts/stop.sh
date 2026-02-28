#!/usr/bin/env bash
set -euo pipefail
docker stop bluegreen-app 2>/dev/null || true
docker rm bluegreen-app 2>/dev/null || true
