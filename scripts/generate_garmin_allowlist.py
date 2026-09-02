#!/usr/bin/env python3
"""Regenerate scripts/garmin-mcp-readonly.sh from the Garmin tool catalog.

Run this after adding or removing an entry in
``paceboard_api.providers.garmin.catalog`` so the launch script and the code stay
in agreement. The generator refuses to emit a tool that matches a mutating name
pattern, which is what makes the shipped script safe by construction.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paceboard_api.providers.garmin import catalog  # noqa: E402

TEMPLATE = '''#!/usr/bin/env bash
# Start the Garmin MCP server with Paceboard's read-only tool allowlist.
#
# The allowlist below is GENERATED from src/paceboard_api/providers/garmin/catalog.py
# by scripts/generate_garmin_allowlist.py. Every entry is asserted at generation
# time not to match a mutating name pattern (set_/add_/create_/update_/delete_/
# log_/upload_/import_/schedule_/unschedule_/upsert_/remove_/request_) and not to
# be one of the download tools, so nothing exposed here can change your Garmin
# account or write to disk.
#
# Regenerate after adding a tool to the catalog:
#     uv run --extra paceboard python scripts/generate_garmin_allowlist.py
#
# Usage:
#     ./scripts/garmin-mcp-readonly.sh          # http://127.0.0.1:8000/mcp
#     GARMIN_MCP_PORT=8010 ./scripts/garmin-mcp-readonly.sh
#
# Authenticate once first with:  uv run garmin-mcp-auth

set -euo pipefail

cd "$(dirname "${{BASH_SOURCE[0]}}")/.."

# Loopback only: this transport performs no authentication, and the tools it
# exposes read your entire Garmin health history.
export GARMIN_MCP_TRANSPORT="${{GARMIN_MCP_TRANSPORT:-streamable-http}}"
export GARMIN_MCP_HOST="${{GARMIN_MCP_HOST:-127.0.0.1}}"
export GARMIN_MCP_PORT="${{GARMIN_MCP_PORT:-8000}}"

# {count} read-only tools.
GARMIN_ENABLED_TOOLS=$(printf '%s' \\
  {body})
export GARMIN_ENABLED_TOOLS

echo "Garmin MCP (read-only, {count} tools)"
echo "  endpoint : http://${{GARMIN_MCP_HOST}}:${{GARMIN_MCP_PORT}}/mcp"
echo "  health   : http://${{GARMIN_MCP_HOST}}:${{GARMIN_MCP_PORT}}/healthz"

exec uv run --python 3.12 garmin-mcp
'''


def build() -> str:
    names = list(catalog.READ_ONLY_ALLOWLIST)
    offenders = [name for name in names if catalog.is_mutating(name)]
    if offenders:
        raise SystemExit(
            "Refusing to generate: catalog contains mutating tools: " + ", ".join(offenders)
        )
    lines, current = [], ""
    for name in names:
        piece = name if not current else f"{current},{name}"
        if len(piece) > 78:
            lines.append(current)
            current = name
        else:
            current = piece
    lines.append(current)
    body = " \\\n  ".join(f'"{line}"' for line in lines)
    return TEMPLATE.format(count=len(names), body=body)


def main() -> int:
    target = ROOT / "scripts" / "garmin-mcp-readonly.sh"
    target.write_text(build())
    target.chmod(0o755)
    print(f"Wrote {target} with {len(catalog.READ_ONLY_ALLOWLIST)} read-only tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
