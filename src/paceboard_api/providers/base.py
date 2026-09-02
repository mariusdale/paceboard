"""The provider boundary.

Everything that reaches Paceboard's database comes through a
:class:`FitnessProvider`. Adapters translate a provider's transport (MCP tools,
REST endpoints) into :class:`~paceboard_api.providers.dto.ProviderResult` values
carrying typed DTOs plus the untouched original response.

Adding a provider means implementing this protocol and registering a normalizer;
no ingestion, API or UI code needs to know the transport.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, Protocol, runtime_checkable

from .dto import (
    ActivitySummaryDTO,
    Capability,
    LapDTO,
    ProviderResult,
    StreamSetDTO,
    ZoneDTO,
)


@runtime_checkable
class FitnessProvider(Protocol):
    """Minimum surface every provider adapter exposes."""

    name: str

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def health(self) -> tuple[bool, str]:
        """``(reachable, human-readable detail)`` — no credentials in the detail."""

    async def discover_capabilities(self) -> list[Capability]: ...

    async def fetch_activities(
        self, start: date, end: date
    ) -> tuple[list[ActivitySummaryDTO], list[ProviderResult]]:
        """Summaries for the window plus the raw results that produced them."""

    async def fetch_activity_detail(
        self, provider_id: str
    ) -> tuple[Optional[ActivitySummaryDTO], list[ProviderResult]]: ...

    async def fetch_activity_laps(
        self, provider_id: str
    ) -> tuple[list[LapDTO], list[ProviderResult]]: ...

    async def fetch_activity_zones(
        self, provider_id: str
    ) -> tuple[list[ZoneDTO], list[ProviderResult]]: ...

    async def fetch_activity_streams(
        self, provider_id: str
    ) -> tuple[Optional[StreamSetDTO], list[ProviderResult]]: ...

    async def fetch_daily(self, day: date, categories: list[str]) -> list[ProviderResult]:
        """Day-scoped health/training calls for one calendar day."""

    async def fetch_range(
        self, start: date, end: date, categories: list[str]
    ) -> list[ProviderResult]: ...

    async def fetch_account(self) -> list[ProviderResult]: ...


class ProviderUnavailable(RuntimeError):
    """Raised when a provider is not configured or cannot be reached at all."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(f"{provider}: {reason}")
        self.provider = provider
        self.reason = reason


def summarize_results(results: list[ProviderResult]) -> dict[str, Any]:
    """Compact status histogram used in sync summaries."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status.value] = counts.get(result.status.value, 0) + 1
    return counts
