#!/usr/bin/env bash
# Start Paceboard in fixture mode for the Playwright suite.
#
# Uses a scratch database under .e2e/ and its own ports, so an e2e run can never
# read or write your real Paceboard database.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

API_PORT="${PACEBOARD_E2E_API_PORT:-8877}"
WEB_PORT="${PACEBOARD_E2E_WEB_PORT:-3100}"
DB=".e2e/paceboard-e2e.sqlite3"

mkdir -p .e2e
rm -f "$DB" "$DB"-wal "$DB"-shm

export PACEBOARD_DATABASE_PATH="$DB"
export PACEBOARD_TOKEN_PATH=".e2e/strava_tokens.json"
export PACEBOARD_SECRET_KEY_PATH=".e2e/paceboard.key"
export PACEBOARD_API_PORT="$API_PORT"
export PACEBOARD_WEB_PORT="$WEB_PORT"
export PACEBOARD_FIXTURE_MODE=true
export PACEBOARD_SCHEDULER_ENABLED=false
export PACEBOARD_LOG_LEVEL=WARNING
# Point the Garmin MCP URL at a closed port: the suite must never reach a real
# provider, and the UI's disconnected state is itself under test.
export GARMIN_MCP_URL="http://127.0.0.1:59999/mcp"
unset STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET 2>/dev/null || true

uv run --extra paceboard paceboard-api seed-fixtures --days 90 >/dev/null

cleanup() {
  trap - INT TERM EXIT
  kill "${API_PID:-}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

uv run --extra paceboard paceboard-api serve --no-migrate &
API_PID=$!

cd dashboard
exec npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort
