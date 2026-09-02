"""MCP bridge that lets Claude write Garmin and Strava results to Paceboard."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

import requests
from mcp.server.fastmcp import FastMCP


app = FastMCP("Paceboard Dashboard")


def _config() -> tuple[str, str]:
    base_url = os.getenv("PACEBOARD_URL", "http://localhost:3000").rstrip("/")
    ingest_key = os.getenv("PACEBOARD_INGEST_KEY", "")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("PACEBOARD_URL must start with http:// or https://")
    return base_url, ingest_key


def _headers(ingest_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if ingest_key:
        headers["Authorization"] = f"Bearer {ingest_key}"
    return headers


@app.tool()
def sync_fitness_data(
    source: Literal["garmin", "strava"],
    activities: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    message: str | None = None,
) -> str:
    """Upsert one Garmin or Strava snapshot into the Paceboard dashboard.

    Use this after retrieving data from the corresponding MCP server. Pass the
    source activity array without inventing missing measurements. Garmin metrics
    should be grouped by tool, for example {"stats": <get_stats result>,
    "sleep": <get_sleep_summary result>, "hrv": <get_hrv_data result>,
    "stress": <get_stress_summary result>, "training_readiness":
    <get_training_readiness result>}. Strava may omit metrics.

    Args:
        source: The MCP source whose data is being written.
        activities: Up to 250 activity dictionaries from that source.
        metrics: Optional named metric results, primarily for Garmin recovery data.
        message: Optional note about the sync or unavailable fields.
    """
    if len(activities) > 250:
        raise ValueError("A single sync supports at most 250 activities")
    base_url, ingest_key = _config()
    response = requests.post(
        f"{base_url}/api/ingest",
        headers=_headers(ingest_key),
        json={
            "source": source,
            "activities": activities,
            "metrics": metrics or {},
            "message": message,
        },
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"body": response.text[:500]}
    if not response.ok:
        raise RuntimeError(f"Paceboard returned HTTP {response.status_code}: {body}")
    return json.dumps(body, indent=2)


@app.tool()
def get_paceboard_status() -> str:
    """Check the Paceboard connection and report currently stored source data."""
    base_url, ingest_key = _config()
    response = requests.get(
        f"{base_url}/api/dashboard",
        headers=_headers(ingest_key),
        timeout=20,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"body": response.text[:500]}
    if not response.ok:
        raise RuntimeError(f"Paceboard returned HTTP {response.status_code}: {body}")
    summary = {
        "status": "connected",
        "dashboard_url": base_url,
        "activity_count": len(body.get("activities", [])),
        "sources": {
            name: {
                "activity_count": snapshot.get("activity_count", 0),
                "synced_at": snapshot.get("synced_at"),
                "message": snapshot.get("message"),
            }
            for name, snapshot in body.get("sources", {}).items()
        },
    }
    return json.dumps(summary, indent=2)


def main() -> None:
    """Run the Paceboard bridge over stdio for Claude Desktop."""
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
