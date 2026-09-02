"""Test harness: an isolated database and a fake Garmin MCP for each test."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Optional

import pytest

from paceboard_api import config as config_module
from paceboard_api.db import session as session_module
from paceboard_api.db.models import Base
from paceboard_api.providers.dto import ProviderResult, ResultStatus
from paceboard_api.providers.garmin.parsing import parse_tool_text

from . import fixtures


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Point every path at a temp directory so tests never touch real data."""
    for key in list(os.environ):
        if key.startswith(("PACEBOARD_", "STRAVA_", "GARMIN_MCP_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PACEBOARD_DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("PACEBOARD_TOKEN_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("PACEBOARD_SECRET_KEY_PATH", str(tmp_path / "key"))
    monkeypatch.setenv("PACEBOARD_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("PACEBOARD_LOG_LEVEL", "WARNING")
    # A frozen .env in the repo must not leak into tests.
    monkeypatch.setattr(config_module, "_load_dotenv", lambda _path: None)
    config_module.reset_settings_cache()
    resolved = config_module.get_settings()
    yield resolved
    config_module.reset_settings_cache()


@pytest.fixture()
def db(settings):
    """A fresh schema created directly from the models."""
    session_module.reset_engine()
    engine = session_module.get_engine()
    Base.metadata.create_all(engine)
    yield session_module
    session_module.reset_engine()


@pytest.fixture()
def session(db):
    with db.session_scope() as active:
        yield active


class FakeMcpClient:
    """Stands in for GarminMcpClient with scripted per-tool responses.

    Responses may be a JSON-serializable object, a raw string (exercising the
    plain-text classifier), a callable, or an exception to raise.
    """

    def __init__(self, responses: Optional[dict[str, Any]] = None,
                 tool_names: Optional[set[str]] = None) -> None:
        self.responses: dict[str, Any] = dict(responses or {})
        self._tool_names = tool_names
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.connected = False
        self.connect_count = 0

    # -- lifecycle
    async def connect(self) -> None:
        self.connected = True
        self.connect_count += 1

    async def close(self) -> None:
        self.connected = False

    async def ping(self) -> tuple[bool, str]:
        return True, f"{len(self.server_tool_names)} tools available"

    @property
    def server_tool_names(self) -> frozenset[str]:
        from paceboard_api.providers.garmin import catalog

        if self._tool_names is not None:
            return frozenset(self._tool_names)
        return frozenset(catalog.TOOLS_BY_NAME)

    def capabilities(self):
        from paceboard_api.providers.garmin.mcp_client import GarminMcpClient

        return GarminMcpClient.capabilities(self)  # type: ignore[arg-type]

    @property
    def _tools(self) -> dict[str, dict[str, Any]]:
        return {name: {"description": "", "input_schema": None} for name in self.server_tool_names}

    # -- calling
    async def call(self, tool: str, arguments: Optional[dict[str, Any]] = None) -> ProviderResult:
        from paceboard_api.providers.garmin import catalog

        arguments = {k: v for k, v in (arguments or {}).items() if v is not None}
        self.calls.append((tool, arguments))
        if catalog.is_mutating(tool):
            raise PermissionError(f"Refusing to call mutating Garmin tool {tool!r}")
        if tool not in self.server_tool_names:
            return ProviderResult(
                provider="garmin", endpoint=tool, params=arguments,
                status=ResultStatus.UNSUPPORTED,
                message=f"Tool {tool!r} is not available on this Garmin MCP server",
            )
        payload = self.responses.get(tool)
        if payload is None:
            return ProviderResult(
                provider="garmin", endpoint=tool, params=arguments,
                status=ResultStatus.NO_DATA, message="No data configured for this tool",
            )
        if isinstance(payload, BaseException):
            raise payload
        if callable(payload):
            payload = payload(arguments)
        text = payload if isinstance(payload, str) else fixtures.as_text(payload)
        status, data, message = parse_tool_text(text)
        return ProviderResult(
            provider="garmin", endpoint=tool, params=arguments, status=status,
            data=data, text=None if data is not None else text, message=message,
            duration_ms=3,
        )


@pytest.fixture()
def garmin_responses() -> dict[str, Any]:
    """A representative, mostly-successful Garmin server."""
    def for_date(template: dict) -> Any:
        """Echo back the requested date, as the real server does."""
        def respond(arguments: dict[str, Any]) -> dict:
            day = arguments.get("date") or arguments.get("end_date")
            return {**template, "date": day} if day else template
        return respond

    def for_activity(template: dict, per_activity: dict | None = None) -> Any:
        """Answer per activity id, defaulting to the template for unknown ids."""
        def respond(arguments: dict[str, Any]) -> dict:
            activity_id = arguments.get("activity_id")
            if activity_id is None:
                return template
            key = int(activity_id)
            payload = (per_activity or {}).get(key, template)
            return {**payload, "id": key, "activity_id": key}
        return respond

    return {
        "get_stats": for_date(fixtures.GARMIN_STATS),
        "get_sleep_summary": for_date(fixtures.GARMIN_SLEEP_SUMMARY),
        "get_sleep_summary_range": fixtures.GARMIN_SLEEP_RANGE,
        "get_hrv_data": for_date(fixtures.GARMIN_HRV),
        "get_stress_summary": for_date(fixtures.GARMIN_STRESS),
        "get_training_status": for_date(fixtures.GARMIN_TRAINING_STATUS),
        "get_training_load_trend": fixtures.GARMIN_LOAD_TREND,
        "get_vo2max_trend": fixtures.GARMIN_VO2MAX_TREND,
        "get_activities_by_date": fixtures.GARMIN_ACTIVITIES,
        "get_activity": for_activity(
            fixtures.GARMIN_ACTIVITY_DETAIL,
            {24188138096: fixtures.GARMIN_RIDE_DETAIL},
        ),
        "get_activity_splits": for_activity(fixtures.GARMIN_ACTIVITY_SPLITS),
        "get_activity_hr_in_timezones": fixtures.GARMIN_HR_ZONES_IN_ACTIVITY,
        "get_activity_fit_messages": for_activity(fixtures.GARMIN_FIT_RECORDS),
        "get_user_profile": fixtures.GARMIN_USER_PROFILE,
        "get_heart_rate_zones": fixtures.GARMIN_HR_ZONE_CONFIG,
        "get_devices": fixtures.GARMIN_DEVICES,
        "get_personal_record": fixtures.GARMIN_PERSONAL_RECORDS,
        "get_body_battery": fixtures.GARMIN_BODY_BATTERY,
        # The failure modes a real server produces.
        "get_gear": fixtures.GARMIN_TEXT_RESPONSES["no_gear"],
        "get_training_readiness": fixtures.GARMIN_TEXT_RESPONSES["no_readiness"],
        "get_running_tolerance": fixtures.GARMIN_TEXT_RESPONSES["unsupported"],
        "get_endurance_score": fixtures.GARMIN_TEXT_RESPONSES["tool_error"],
        "get_weigh_ins": fixtures.GARMIN_TEXT_RESPONSES["no_weight"],
        "get_spo2_data": fixtures.GARMIN_EMPTY_JSON[0],
    }


@pytest.fixture()
def fake_client(garmin_responses) -> FakeMcpClient:
    return FakeMcpClient(garmin_responses)


@pytest.fixture()
def garmin_provider(fake_client):
    from paceboard_api.providers.garmin.provider import GarminMcpProvider

    return GarminMcpProvider(fake_client)


def run(coro):
    """Run a coroutine from a synchronous test."""
    return asyncio.get_event_loop().run_until_complete(coro)
