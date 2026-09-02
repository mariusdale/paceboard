"""GarminMcpClient behaviour: allowlisting, retries, reconnect and timeouts."""

from __future__ import annotations

import asyncio

import pytest

from paceboard_api.providers.dto import ResultStatus
from paceboard_api.providers.garmin import catalog
from paceboard_api.providers.garmin.mcp_client import (
    GarminMcpClient,
    GarminMcpUnavailable,
)


class StubSession:
    """A minimal ClientSession stand-in with a scripted call sequence."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        action = self.script.pop(0) if self.script else ("text", "No data found.")
        kind, payload = action
        if kind == "raise":
            raise payload
        if kind == "hang":
            await asyncio.sleep(10)
        return _Result(payload, is_error=(kind == "error"))


class _Result:
    def __init__(self, text, is_error=False):
        self.content = [_Text(text)]
        self.isError = is_error


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


def make_client(session, **kwargs) -> GarminMcpClient:
    client = GarminMcpClient("http://127.0.0.1:8000/mcp", **kwargs)
    client._session = session
    client._tools = {name: {"description": "", "input_schema": None}
                     for name in catalog.TOOLS_BY_NAME}
    client._generation = 1
    return client


class TestAllowlist:
    async def test_mutating_tool_is_refused_before_any_network_call(self):
        session = StubSession([])
        client = make_client(session)
        with pytest.raises(PermissionError, match="mutating"):
            await client.call("set_activity_name", {"activity_id": "1"})
        assert session.calls == []

    @pytest.mark.parametrize(
        "tool",
        ["create_run_workout", "delete_workout", "add_weigh_in", "upload_course",
         "schedule_workout", "log_food", "request_reload", "download_activity_file"],
    )
    def test_no_mutating_tool_is_in_the_catalog(self, tool):
        assert tool not in catalog.TOOLS_BY_NAME
        assert catalog.is_mutating(tool)

    async def test_unknown_tool_reports_unsupported(self):
        client = make_client(StubSession([]))
        client._tools = {}
        result = await client.call("get_totally_made_up_metric", {})
        assert result.status is ResultStatus.UNSUPPORTED


class TestRetries:
    async def test_transient_protocol_error_is_retried_then_succeeds(self, monkeypatch):
        session = StubSession([
            ("raise", ConnectionResetError("socket closed")),
            ("text", '{"total_steps": 100}'),
        ])
        client = make_client(session, max_retries=2)
        monkeypatch.setattr(client, "_reconnect", _noop)
        monkeypatch.setattr(GarminMcpClient, "_backoff", staticmethod(lambda *_: 0.0))

        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.ok
        assert len(session.calls) == 2

    async def test_permanent_no_data_is_never_retried(self):
        session = StubSession([("text", "No gear found."), ("text", '{"a": 1}')])
        client = make_client(session, max_retries=3)
        result = await client.call("get_gear", {})
        assert result.status is ResultStatus.NO_DATA
        assert len(session.calls) == 1, "a permanent result must not be retried"

    async def test_unsupported_is_never_retried(self):
        session = StubSession([("text", "Your device does not support this metric.")])
        client = make_client(session, max_retries=3)
        result = await client.call("get_running_tolerance", {"date": "2026-08-20"})
        assert result.status is ResultStatus.UNSUPPORTED
        assert len(session.calls) == 1

    async def test_retries_give_up_and_report_the_last_status(self, monkeypatch):
        session = StubSession([("raise", ConnectionResetError())] * 5)
        client = make_client(session, max_retries=2)
        monkeypatch.setattr(client, "_reconnect", _noop)
        monkeypatch.setattr(GarminMcpClient, "_backoff", staticmethod(lambda *_: 0.0))
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.status is ResultStatus.PROTOCOL_ERROR
        assert len(session.calls) == 3  # initial attempt plus two retries

    async def test_rate_limit_backoff_is_longer_than_a_normal_retry(self):
        rate = GarminMcpClient._backoff(ResultStatus.RATE_LIMITED, 1)
        normal = GarminMcpClient._backoff(ResultStatus.PROTOCOL_ERROR, 1)
        assert rate > normal * 4

    async def test_backoff_grows_and_is_jittered(self):
        first = [GarminMcpClient._backoff(ResultStatus.TIMEOUT, 1) for _ in range(30)]
        second = GarminMcpClient._backoff(ResultStatus.TIMEOUT, 3)
        assert len(set(first)) > 1, "backoff must be jittered"
        assert second > max(first)


class TestTimeout:
    async def test_a_hanging_call_times_out_rather_than_blocking(self, monkeypatch):
        session = StubSession([("hang", None)])
        client = make_client(session, timeout=0.05, max_retries=0)
        monkeypatch.setattr(client, "_reconnect", _noop)
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.status is ResultStatus.TIMEOUT
        assert "timed out" in result.message


class TestReconnect:
    async def test_a_dead_session_triggers_one_reconnect(self, monkeypatch):
        session = StubSession([
            ("raise", ConnectionResetError()),
            ("text", '{"total_steps": 1}'),
        ])
        client = make_client(session, max_retries=1)
        attempts = []

        async def record(generation):
            attempts.append(generation)

        monkeypatch.setattr(client, "_reconnect", record)
        monkeypatch.setattr(GarminMcpClient, "_backoff", staticmethod(lambda *_: 0.0))
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.ok
        assert attempts == [1]

    async def test_failed_reconnect_surfaces_its_reason(self, monkeypatch):
        session = StubSession([("raise", ConnectionResetError())])
        client = make_client(session, max_retries=0)

        async def failing(_generation):
            raise GarminMcpUnavailable("Cannot reach Garmin MCP at http://x/mcp")

        monkeypatch.setattr(client, "_reconnect", failing)
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.status is ResultStatus.PROTOCOL_ERROR
        assert "Cannot reach Garmin MCP" in result.message

    async def test_connect_failure_raises_a_typed_error(self):
        client = GarminMcpClient("http://127.0.0.1:59999/mcp", timeout=0.4)
        with pytest.raises(GarminMcpUnavailable):
            await client.connect()
        await client.close()


class TestToolErrorFlag:
    async def test_is_error_result_is_classified_from_its_text(self):
        session = StubSession([("error", "Garmin rate limit hit. Wait a few minutes.")])
        client = make_client(session, max_retries=0)
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.status is ResultStatus.RATE_LIMITED

    async def test_is_error_with_json_body_still_reports_an_error(self):
        session = StubSession([("error", '{"detail": "boom"}')])
        client = make_client(session, max_retries=0)
        result = await client.call("get_stats", {"date": "2026-08-20"})
        assert result.status is ResultStatus.ERROR


class TestCapabilities:
    def test_missing_tools_are_recorded_as_unavailable(self):
        client = make_client(StubSession([]))
        client._tools = {"get_stats": {"description": "d", "input_schema": None}}
        capabilities = {c.name: c for c in client.capabilities()}
        assert capabilities["get_stats"].status == "available"
        assert capabilities["get_hrv_data"].status == "unavailable"
        assert capabilities["get_hrv_data"].enabled is False

    def test_extra_read_tools_are_recorded_as_unmapped(self):
        client = make_client(StubSession([]))
        client._tools["get_some_new_metric"] = {"description": "new", "input_schema": None}
        capabilities = {c.name: c for c in client.capabilities()}
        assert capabilities["get_some_new_metric"].status == "unmapped"
        assert capabilities["get_some_new_metric"].enabled is False

    def test_mutating_server_tools_are_never_catalogued(self):
        client = make_client(StubSession([]))
        client._tools["delete_workout"] = {"description": "", "input_schema": None}
        names = {c.name for c in client.capabilities()}
        assert "delete_workout" not in names


async def _noop(*_args, **_kwargs):
    return None
