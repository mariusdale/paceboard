"""Runtime configuration for the Paceboard backend.

Every setting is overridable through the environment (or a local ``.env``).
Defaults are chosen so a fresh checkout runs locally with no configuration:
loopback bind, SQLite under ``./data``, Garmin MCP on its documented port and
no Strava credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]

_TRUTHY = {"1", "true", "yes", "on"}


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a ``.env`` file without overriding it.

    Deliberately hand-rolled: the backend must not depend on the Garmin MCP's
    dotenv pinning, and the format Paceboard needs is only ``KEY=value``.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    return raw.lower() in _TRUTHY if raw else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of Paceboard's configuration."""

    # --- HTTP -------------------------------------------------------------
    host: str = "127.0.0.1"
    api_port: int = 8787
    web_port: int = 3000
    allow_non_loopback: bool = False
    max_request_bytes: int = 2 * 1024 * 1024

    # --- Storage ----------------------------------------------------------
    database_path: Path = REPO_ROOT / "data" / "paceboard.sqlite3"
    token_path: Path = REPO_ROOT / "data" / "strava_tokens.json"
    secret_key_path: Path = REPO_ROOT / "data" / "paceboard.key"

    # --- Locale -----------------------------------------------------------
    timezone: str = "Europe/Oslo"
    unit_system: str = "metric"

    # --- Garmin MCP -------------------------------------------------------
    garmin_mcp_url: str = "http://127.0.0.1:8000/mcp"
    garmin_mcp_timeout: float = 120.0
    garmin_mcp_concurrency: int = 3
    garmin_mcp_max_retries: int = 3

    # --- Strava -----------------------------------------------------------
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_redirect_uri: str = "http://127.0.0.1:8787/api/v1/auth/strava/callback"
    strava_webhook_verify_token: str = ""
    strava_poll_minutes: int = 60

    # --- Sync -------------------------------------------------------------
    backfill_days: int = 90
    reconcile_days: int = 3
    scheduler_enabled: bool = True
    fast_interval_minutes: int = 15
    daily_hour_local: int = 4

    # --- Dedupe tolerances ------------------------------------------------
    dedupe_start_tolerance_seconds: int = 300
    dedupe_duration_tolerance_pct: float = 0.05
    dedupe_distance_tolerance_pct: float = 0.05

    # --- Modes ------------------------------------------------------------
    fixture_mode: bool = False
    log_level: str = "INFO"

    extra_origins: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path}"

    @property
    def async_database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def strava_configured(self) -> bool:
        return bool(self.strava_client_id and self.strava_client_secret)

    @property
    def cors_origins(self) -> list[str]:
        """Only the local dashboard origins are permitted to call the API."""
        origins = {
            f"http://127.0.0.1:{self.web_port}",
            f"http://localhost:{self.web_port}",
        }
        origins.update(self.extra_origins)
        return sorted(origins)

    @property
    def is_loopback(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}


def _resolve_path(value: str, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def build_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    defaults = Settings()
    extra = tuple(
        origin.strip()
        for origin in _env("PACEBOARD_EXTRA_ORIGINS").split(",")
        if origin.strip()
    )
    return Settings(
        host=_env("PACEBOARD_HOST", defaults.host),
        api_port=_env_int("PACEBOARD_API_PORT", defaults.api_port),
        web_port=_env_int("PACEBOARD_WEB_PORT", defaults.web_port),
        allow_non_loopback=_env_bool("PACEBOARD_ALLOW_NON_LOOPBACK", False),
        max_request_bytes=_env_int("PACEBOARD_MAX_REQUEST_BYTES", defaults.max_request_bytes),
        database_path=_resolve_path(_env("PACEBOARD_DATABASE_PATH"), defaults.database_path),
        token_path=_resolve_path(_env("PACEBOARD_TOKEN_PATH"), defaults.token_path),
        secret_key_path=_resolve_path(_env("PACEBOARD_SECRET_KEY_PATH"), defaults.secret_key_path),
        timezone=_env("PACEBOARD_TIMEZONE", defaults.timezone),
        unit_system=_env("PACEBOARD_UNIT_SYSTEM", defaults.unit_system),
        garmin_mcp_url=_env("GARMIN_MCP_URL", defaults.garmin_mcp_url),
        garmin_mcp_timeout=_env_float("GARMIN_MCP_TIMEOUT", defaults.garmin_mcp_timeout),
        garmin_mcp_concurrency=_env_int("GARMIN_MCP_CONCURRENCY", defaults.garmin_mcp_concurrency),
        garmin_mcp_max_retries=_env_int("GARMIN_MCP_MAX_RETRIES", defaults.garmin_mcp_max_retries),
        strava_client_id=_env("STRAVA_CLIENT_ID"),
        strava_client_secret=_env("STRAVA_CLIENT_SECRET"),
        strava_redirect_uri=_env("STRAVA_REDIRECT_URI", defaults.strava_redirect_uri),
        strava_webhook_verify_token=_env("STRAVA_WEBHOOK_VERIFY_TOKEN"),
        strava_poll_minutes=_env_int("STRAVA_POLL_MINUTES", defaults.strava_poll_minutes),
        backfill_days=_env_int("PACEBOARD_BACKFILL_DAYS", defaults.backfill_days),
        reconcile_days=_env_int("PACEBOARD_RECONCILE_DAYS", defaults.reconcile_days),
        scheduler_enabled=_env_bool("PACEBOARD_SCHEDULER_ENABLED", True),
        fast_interval_minutes=_env_int("PACEBOARD_FAST_INTERVAL_MINUTES", defaults.fast_interval_minutes),
        daily_hour_local=_env_int("PACEBOARD_DAILY_HOUR_LOCAL", defaults.daily_hour_local),
        dedupe_start_tolerance_seconds=_env_int(
            "PACEBOARD_DEDUPE_START_TOLERANCE_SECONDS", defaults.dedupe_start_tolerance_seconds
        ),
        dedupe_duration_tolerance_pct=_env_float(
            "PACEBOARD_DEDUPE_DURATION_TOLERANCE_PCT", defaults.dedupe_duration_tolerance_pct
        ),
        dedupe_distance_tolerance_pct=_env_float(
            "PACEBOARD_DEDUPE_DISTANCE_TOLERANCE_PCT", defaults.dedupe_distance_tolerance_pct
        ),
        fixture_mode=_env_bool("PACEBOARD_FIXTURE_MODE", False),
        log_level=_env("PACEBOARD_LOG_LEVEL", defaults.log_level).upper(),
        extra_origins=extra,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()


def reset_settings_cache() -> None:
    """Drop the cached settings (used by tests that mutate the environment)."""
    get_settings.cache_clear()
