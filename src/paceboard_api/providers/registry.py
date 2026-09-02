"""Provider registry — the single place that knows which adapters exist."""

from __future__ import annotations

from typing import Optional

from ..config import Settings, get_settings
from ..logging_conf import get_logger
from .garmin.provider import GarminMcpProvider
from .strava.provider import StravaApiProvider

log = get_logger("paceboard.registry")

PROVIDER_NAMES = ("garmin", "strava")


class ProviderRegistry:
    """Lazily constructs and caches one adapter instance per provider."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._garmin: Optional[GarminMcpProvider] = None
        self._strava: Optional[StravaApiProvider] = None

    @property
    def garmin(self) -> GarminMcpProvider:
        if self._garmin is None:
            self._garmin = GarminMcpProvider.from_settings(self.settings)
        return self._garmin

    @property
    def strava(self) -> StravaApiProvider:
        if self._strava is None:
            self._strava = StravaApiProvider.from_settings(self.settings)
        return self._strava

    def get(self, name: str):
        if name == "garmin":
            return self.garmin
        if name == "strava":
            return self.strava
        raise KeyError(f"Unknown provider {name!r}")

    async def aclose(self) -> None:
        for provider in (self._garmin, self._strava):
            if provider is not None:
                try:
                    await provider.close()
                except Exception:  # pragma: no cover - shutdown best effort
                    log.debug("Error closing provider", exc_info=True)
        self._garmin = None
        self._strava = None


_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
