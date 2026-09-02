#!/usr/bin/env bash
# Start Paceboard: API + dashboard, both on loopback. Ctrl-C stops both.
#
#   ./scripts/dev.sh
#
# The Garmin MCP server is started separately (it owns your Garmin session):
#   ./scripts/garmin-mcp-readonly.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Load .env so the ports below match what the app will actually bind.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env)
  set +a
fi

HOST="${PACEBOARD_HOST:-127.0.0.1}"
API_PORT="${PACEBOARD_API_PORT:-8787}"
WEB_PORT="${PACEBOARD_WEB_PORT:-3000}"
GARMIN_URL="${GARMIN_MCP_URL:-http://127.0.0.1:8000/mcp}"

if [[ ! -d dashboard/node_modules ]]; then
  echo "Installing dashboard dependencies…"
  (cd dashboard && npm install)
fi

echo "Applying database migrations…"
uv run --extra paceboard paceboard-api migrate

# Warn early rather than letting the first sync fail with a connection error.
HEALTH_URL="${GARMIN_URL%/mcp}/healthz"
if ! curl -fsS -m 2 "$HEALTH_URL" >/dev/null 2>&1; then
  echo
  echo "  ! Garmin MCP is not answering at $HEALTH_URL"
  echo "    Paceboard will start, but Garmin syncs will fail until you run:"
  echo "        ./scripts/garmin-mcp-readonly.sh"
  echo
fi

pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

uv run --extra paceboard paceboard-api serve --no-migrate &
pids+=($!)

(cd dashboard && PACEBOARD_API_PORT="$API_PORT" PACEBOARD_WEB_PORT="$WEB_PORT" npm run dev -- --host "$HOST") &
pids+=($!)

sleep 2
cat <<BANNER

  Paceboard is running (loopback only)

    Dashboard   http://${HOST}:${WEB_PORT}
    REST API    http://${HOST}:${API_PORT}/api/v1
    API docs    http://${HOST}:${API_PORT}/docs
    Garmin MCP  ${GARMIN_URL}

  Press Ctrl-C to stop both processes.

BANNER

wait
