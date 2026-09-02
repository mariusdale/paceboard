"""StravaMcpProvider — deliberately not implemented as a runtime ingestion path.

Investigation result (recorded here so it is not re-litigated):

The Strava integration available in this environment is a **Claude-managed**
connector — its tools (``mcp__claude_ai_Strava__*``) are exposed inside Claude's
own MCP host and authenticated by Claude's OAuth session. There is no local
endpoint, socket, or command an external process can attach to, and the only way
to make one would be to lift Claude's credentials, which is exactly what the
project constraints forbid.

Therefore:

* runtime Strava ingestion uses :class:`StravaApiProvider` (official REST API);
* the Claude Strava connector remains useful for *schema inspection* — confirming
  field names and response shapes while developing the adapter — and was used
  that way only;
* this class exists so the provider registry has a named, documented slot if a
  reusable local Strava MCP endpoint ever appears. Constructing it raises with an
  explanation rather than silently degrading.

If such an endpoint does appear, implement it against the same
:class:`~paceboard_api.providers.base.FitnessProvider` protocol and register it
in :mod:`paceboard_api.providers.registry`; nothing downstream needs to change.
"""

from __future__ import annotations

REASON = (
    "The Strava MCP integration in this environment is Claude-managed: it has no "
    "local endpoint an external process can reuse, and copying Claude's "
    "credentials is not permitted. Paceboard ingests Strava through the official "
    "REST API instead (StravaApiProvider)."
)


class StravaMcpProvider:
    """Placeholder for a reusable local Strava MCP endpoint (none exists today)."""

    name = "strava_mcp"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise NotImplementedError(REASON)

    @staticmethod
    def availability() -> dict[str, object]:
        """Machine-readable status shown in the Connections page."""
        return {
            "provider": "strava_mcp",
            "available": False,
            "reason": REASON,
        }
