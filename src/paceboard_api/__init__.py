"""Paceboard — local-first personal fitness analytics backend.

Paceboard ingests Garmin (via the read-only Garmin MCP server in this repo) and
Strava (via the official REST API) into a local SQLite database, derives
analytics from the normalized data, and serves it over a local REST API.
"""

__version__ = "1.0.0"
