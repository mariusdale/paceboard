"""Persistent, read-only MCP client for the Garmin MCP server.

Responsibilities beyond "call a tool":

* one initialized session, reused across a whole sync, reconnected transparently
  if the server restarts mid-run;
* a capability catalog captured from ``tools/list`` at connect time, so a tool
  that this watch/account does not expose is recorded as unavailable instead of
  producing repeated failures;
* bounded concurrency plus timeouts, jittered retries and rate-limit backoff,
  with permanent failures (no data, unsupported, bad arguments) never retried;
* per-call telemetry — tool name, argument *keys*, duration, status — recorded
  without ever logging a response body.

The client refuses to invoke anything outside
:data:`~paceboard_api.providers.garmin.catalog.READ_ONLY_ALLOWLIST`; that check
is enforced here rather than only at the API edge so no internal caller can
reach a mutating tool either.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ...logging_conf import get_logger
from ..dto import Capability, ProviderResult, ResultStatus
from . import catalog
from .parsing import extract_text, parse_tool_text

log = get_logger("paceboard.garmin.mcp")

_RETRY_BASE_SECONDS = 1.5
_RATE_LIMIT_BASE_SECONDS = 20.0


class GarminMcpUnavailable(RuntimeError):
    """The MCP server could not be reached or initialized."""


class GarminMcpClient:
    """An async client wrapping one streamable-HTTP MCP session."""

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 120.0,
        concurrency: int = 3,
        max_retries: int = 3,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._connect_lock = asyncio.Lock()
        self._runner: Optional[asyncio.Task[None]] = None
        self._shutdown = asyncio.Event()
        self._ready = asyncio.Event()
        self._open_error: Optional[BaseException] = None
        self._session: Any = None
        self._tools: dict[str, dict[str, Any]] = {}
        self._connected_at: Optional[datetime] = None
        self._generation = 0

    # -- connection ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._session is not None

    @property
    def connected_at(self) -> Optional[datetime]:
        return self._connected_at

    async def connect(self) -> None:
        async with self._connect_lock:
            await self._open_locked()

    async def _open_locked(self) -> None:
        """Start the session-owner task and wait until it is initialized.

        The streamable-HTTP transport and ``ClientSession`` are anyio context
        managers whose cancel scopes belong to the task that entered them, so a
        single dedicated task owns them for the session's whole life. The
        resulting ``ClientSession`` object is itself safe to call from other
        tasks, which is what gives us concurrency without cross-task scope
        errors.
        """
        if self._session is not None:
            return
        self._shutdown = asyncio.Event()
        self._ready = asyncio.Event()
        self._open_error = None
        self._runner = asyncio.create_task(self._run_session(), name="garmin-mcp-session")
        await self._ready.wait()
        if self._open_error is not None:
            error, self._open_error = self._open_error, None
            self._runner = None
            raise error

    async def _run_session(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with streamablehttp_client(self.url, timeout=self.timeout) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=self.timeout)
                    listing = await asyncio.wait_for(
                        session.list_tools(), timeout=self.timeout
                    )
                    self._session = session
                    self._connected_at = datetime.now(timezone.utc)
                    self._generation += 1
                    self._tools = {
                        tool.name: {
                            "description": (tool.description or "").strip(),
                            "input_schema": getattr(tool, "inputSchema", None),
                        }
                        for tool in listing.tools
                    }
                    log.info(
                        "Garmin MCP session established",
                        extra={
                            "url": self.url,
                            "tool_count": len(self._tools),
                            "generation": self._generation,
                        },
                    )
                    self._ready.set()
                    await self._shutdown.wait()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception as exc:
            self._open_error = GarminMcpUnavailable(
                f"Cannot reach Garmin MCP at {self.url}: {type(exc).__name__}: "
                f"{str(exc)[:200]}"
            )
        finally:
            self._session = None
            self._ready.set()

    async def _reconnect(self, generation: int) -> None:
        """Reopen the session unless another task already did it for us."""
        async with self._connect_lock:
            if self._generation != generation and self._session is not None:
                return
            await self._close_locked()
            await self._open_locked()

    async def _close_locked(self) -> None:
        runner, self._runner = self._runner, None
        self._session = None
        if runner is None:
            return
        self._shutdown.set()
        try:
            await asyncio.wait_for(runner, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
            runner.cancel()
        except Exception:  # pragma: no cover - best-effort teardown
            log.debug("Error while closing Garmin MCP session", exc_info=True)

    async def close(self) -> None:
        async with self._connect_lock:
            await self._close_locked()

    async def __aenter__(self) -> "GarminMcpClient":
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # -- capabilities ----------------------------------------------------

    @property
    def server_tool_names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def capabilities(self) -> list[Capability]:
        """Reconcile Paceboard's catalog against what the server registered."""
        available = self.server_tool_names
        caps: list[Capability] = []
        for spec in catalog.TOOL_SPECS:
            info = self._tools.get(spec.name, {})
            caps.append(
                Capability(
                    name=spec.name,
                    category=spec.category,
                    scope=spec.scope,
                    cadence=spec.cadence,
                    handler=spec.handler,
                    enabled=spec.enabled and spec.name in available,
                    description=info.get("description", "") or spec.notes,
                    expected_arguments={"required": list(spec.args), **spec.extra_args},
                    status="available" if spec.name in available else "unavailable",
                    input_schema=info.get("input_schema"),
                )
            )
        # Tools the server exposes that Paceboard has no mapping for: recorded so
        # the Data Explorer can show full provider coverage.
        for name in sorted(available - set(catalog.TOOLS_BY_NAME)):
            if catalog.is_mutating(name):
                continue
            caps.append(
                Capability(
                    name=name,
                    category="unmapped",
                    scope="unknown",
                    cadence="on_demand",
                    handler=None,
                    enabled=False,
                    description=self._tools[name].get("description", ""),
                    status="unmapped",
                    input_schema=self._tools[name].get("input_schema"),
                )
            )
        return caps

    # -- calling ---------------------------------------------------------

    async def call(
        self, tool: str, arguments: Optional[dict[str, Any]] = None
    ) -> ProviderResult:
        """Invoke one read-only tool, with retries and full status classification."""
        arguments = {k: v for k, v in (arguments or {}).items() if v is not None}
        if catalog.is_mutating(tool):
            raise PermissionError(f"Refusing to call mutating Garmin tool {tool!r}")
        if tool not in catalog.TOOLS_BY_NAME and tool not in self._tools:
            return ProviderResult(
                provider="garmin", endpoint=tool, params=arguments,
                status=ResultStatus.UNSUPPORTED,
                message=f"Tool {tool!r} is not available on this Garmin MCP server",
            )
        async with self._semaphore:
            return await self._call_with_retries(tool, arguments)

    async def _call_with_retries(
        self, tool: str, arguments: dict[str, Any]
    ) -> ProviderResult:
        attempt = 0
        started_all = time.perf_counter()
        while True:
            generation = self._generation
            started = time.perf_counter()
            try:
                if self._session is None:
                    await self.connect()
                result = await asyncio.wait_for(
                    self._session.call_tool(tool, arguments), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                outcome = ProviderResult(
                    provider="garmin", endpoint=tool, params=arguments,
                    status=ResultStatus.TIMEOUT,
                    message=f"Garmin MCP call timed out after {self.timeout:g}s",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            except (GarminMcpUnavailable, Exception) as exc:
                # Transport/protocol failure — the session may be dead; drop it so
                # the next attempt reconnects.
                outcome = ProviderResult(
                    provider="garmin", endpoint=tool, params=arguments,
                    status=ResultStatus.PROTOCOL_ERROR,
                    message=f"{type(exc).__name__}: {str(exc)[:200]}",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                try:
                    await self._reconnect(generation)
                except GarminMcpUnavailable as reconnect_exc:
                    outcome.message = str(reconnect_exc)
            else:
                text = extract_text(result.content)
                if getattr(result, "isError", False):
                    status, _, message = parse_tool_text(text)
                    if status is ResultStatus.OK:
                        status, message = ResultStatus.ERROR, text[:300]
                    outcome = ProviderResult(
                        provider="garmin", endpoint=tool, params=arguments,
                        status=status, text=text, message=message,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                else:
                    status, data, message = parse_tool_text(text)
                    outcome = ProviderResult(
                        provider="garmin", endpoint=tool, params=arguments,
                        status=status, data=data,
                        text=None if data is not None else text,
                        message=message,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )

            self._log_call(tool, arguments, outcome, attempt)

            if outcome.ok or outcome.status.is_permanent or attempt >= self.max_retries:
                outcome.duration_ms = int((time.perf_counter() - started_all) * 1000)
                return outcome

            attempt += 1
            await asyncio.sleep(self._backoff(outcome.status, attempt))

    @staticmethod
    def _backoff(status: ResultStatus, attempt: int) -> float:
        base = (
            _RATE_LIMIT_BASE_SECONDS
            if status is ResultStatus.RATE_LIMITED
            else _RETRY_BASE_SECONDS
        )
        return base * (2 ** (attempt - 1)) * (0.75 + random.random() * 0.5)

    @staticmethod
    def _log_call(
        tool: str, arguments: dict[str, Any], outcome: ProviderResult, attempt: int
    ) -> None:
        """Record telemetry. Argument *keys* only; never response bodies."""
        level = (
            log.debug
            if outcome.ok or outcome.status in {ResultStatus.NO_DATA, ResultStatus.UNSUPPORTED}
            else log.warning
        )
        level(
            "garmin tool call",
            extra={
                "tool": tool,
                "arg_keys": ",".join(sorted(arguments)),
                "status": outcome.status.value,
                "duration_ms": outcome.duration_ms,
                "attempt": attempt,
                "note": (outcome.message or "")[:160],
            },
        )

    async def ping(self) -> tuple[bool, str]:
        """Cheap liveness probe used by /connections and Settings."""
        try:
            await self.connect()
        except GarminMcpUnavailable as exc:
            return False, str(exc)
        return True, f"{len(self._tools)} tools available"
