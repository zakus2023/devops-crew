#!/usr/bin/env bash
set -euo pipefail
curl -sf http://localhost:8080/health || exit 1
