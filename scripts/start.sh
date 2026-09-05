#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env || ! -f dashboard/dist/index.html || ! -d .venv ]]; then
  echo "Run ./scripts/setup.sh first."
  exit 1
fi
exec uv run --locked --python 3.12 --extra paceboard python scripts/run_local.py
