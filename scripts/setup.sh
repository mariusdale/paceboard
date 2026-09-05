#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in uv node npm; do
  if ! command -v "$tool" >/dev/null; then
    echo "Missing $tool. Install Node.js 22+ from https://nodejs.org and uv from https://docs.astral.sh/uv/getting-started/installation/ then run ./scripts/setup.sh again."
    exit 1
  fi
done
node -e 'if(Number(process.versions.node.split(".")[0])<22){console.error("Node.js 22 or newer is required.");process.exit(1)}'
uv sync --locked --python 3.12 --extra paceboard
npm --prefix dashboard ci
npm --prefix dashboard run build
uv run --locked --python 3.12 --extra paceboard python scripts/onboard.py
