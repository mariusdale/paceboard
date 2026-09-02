"""Strava REST client: OAuth 2.0, automatic refresh, rate-limit awareness.

Implements the complete authorization-code flow (authorize URL → callback →
code exchange → refresh → deauthorize) plus the read endpoints Paceboard
ingests. All requests carry a short timeout and every response's rate-limit
headers are recorded, so the sync orchestrator can back off before Strava
starts returning 429s rather than after.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ...logging_conf import get_logger
from ..dto import ProviderResult, ResultStatus
from .tokens import StravaTokens, TokenStore

log = get_logger("paceboard.strava.client")

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
API_BASE = "https://www.strava.com/api/v3"

#: Read-only scopes. Paceboard never writes to Strava.
DEFAULT_SCOPES = "read,activity:read_all,profile:read_all"

STREAM_KEYS = (
    "time", "distance", "latlng", "altitude", "velocity_smooth", "heartrate",
    "cadence", "watts", "temp", "moving", "grade_smooth",
)


class StravaNotConnected(RuntimeError):
    """No usable Strava credentials/tokens exist."""


@dataclass
class RateLimitState:
    """Mirror of Strava's ``X-RateLimit-*`` / ``X-ReadRateLimit-*`` headers."""

    short_limit: Optional[int] = None
    short_usage: Optional[int] = None
    daily_limit: Optional[int] = None
    daily_usage: Optional[int] = None
    read_short_limit: Optional[int] = None
    read_short_usage: Optional[int] = None
    read_daily_limit: Optional[int] = None
    read_daily_usage: Optional[int] = None
    updated_at: Optional[datetime] = None

    def update(self, headers: httpx.Headers) -> None:
        def pair(name: str) -> tuple[Optional[int], Optional[int]]:
            raw = headers.get(name)
            if not raw or "," not in raw:
                return None, None
            short, _, daily = raw.partition(",")
            try:
                return int(short.strip()), int(daily.strip())
            except ValueError:
                return None, None

        self.short_limit, self.daily_limit = pair("X-RateLimit-Limit")
        self.short_usage, self.daily_usage = pair("X-RateLimit-Usage")
        self.read_short_limit, self.read_daily_limit = pair("X-ReadRateLimit-Limit")
        self.read_short_usage, self.read_daily_usage = pair("X-ReadRateLimit-Usage")
        self.updated_at = datetime.now(timezone.utc)

    @property
    def short_remaining(self) -> Optional[int]:
        if self.short_limit is None or self.short_usage is None:
            return None
        return max(0, self.short_limit - self.short_usage)

    @property
    def daily_remaining(self) -> Optional[int]:
        if self.daily_limit is None or self.daily_usage is None:
            return None
        return max(0, self.daily_limit - self.daily_usage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "short_limit": self.short_limit,
            "short_usage": self.short_usage,
            "short_remaining": self.short_remaining,
            "daily_limit": self.daily_limit,
            "daily_usage": self.daily_usage,
            "daily_remaining": self.daily_remaining,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class _PendingState:
    value: str
    created_at: float = field(default_factory=time.time)


class StravaClient:
    """Thin async wrapper over Strava's v3 API with token lifecycle handling."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        store: TokenStore,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.store = store
        self.timeout = timeout
        self.rate_limit = RateLimitState()
        self._http: Optional[httpx.AsyncClient] = None
        self._refresh_lock = asyncio.Lock()
        self._pending_states: dict[str, _PendingState] = {}

    # -- lifecycle -------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def connected(self) -> bool:
        return self.configured and self.store.load() is not None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    # -- OAuth -----------------------------------------------------------

    def authorization_url(self, scopes: str = DEFAULT_SCOPES) -> tuple[str, str]:
        """Build the consent URL and remember its anti-CSRF ``state``."""
        if not self.configured:
            raise StravaNotConnected(
                "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET are not configured"
            )
        state = secrets.token_urlsafe(24)
        self._prune_states()
        self._pending_states[state] = _PendingState(state)
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": scopes,
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}", state

    def consume_state(self, state: Optional[str]) -> bool:
        self._prune_states()
        if not state:
            return False
        return self._pending_states.pop(state, None) is not None

    def _prune_states(self, max_age_seconds: float = 900.0) -> None:
        cutoff = time.time() - max_age_seconds
        for key, pending in list(self._pending_states.items()):
            if pending.created_at < cutoff:
                self._pending_states.pop(key, None)

    async def exchange_code(self, code: str) -> StravaTokens:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        data = await self._token_request(payload)
        athlete = data.get("athlete") or {}
        tokens = StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
            scope=data.get("scope", ""),
            athlete_id=str(athlete.get("id", "")),
            athlete_name=" ".join(
                part for part in (athlete.get("firstname"), athlete.get("lastname")) if part
            ).strip(),
        )
        self.store.save(tokens)
        return tokens

    async def refresh(self, tokens: StravaTokens) -> StravaTokens:
        data = await self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": tokens.refresh_token,
                "grant_type": "refresh_token",
            }
        )
        refreshed = StravaTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", tokens.refresh_token),
            expires_at=int(data["expires_at"]),
            scope=tokens.scope,
            athlete_id=tokens.athlete_id,
            athlete_name=tokens.athlete_name,
        )
        self.store.save(refreshed)
        log.info("Refreshed Strava access token")
        return refreshed

    async def _token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        http = await self._client()
        response = await http.post(TOKEN_URL, data=payload)
        if response.status_code >= 400:
            # Never echo the body: it can contain the submitted code/secret.
            raise StravaNotConnected(
                f"Strava token endpoint returned HTTP {response.status_code}"
            )
        return response.json()

    async def access_token(self) -> str:
        tokens = self.store.load()
        if tokens is None:
            raise StravaNotConnected("Strava is not connected")
        if tokens.is_expired():
            async with self._refresh_lock:
                tokens = self.store.load() or tokens
                if tokens.is_expired():
                    tokens = await self.refresh(tokens)
        return tokens.access_token

    async def disconnect(self) -> bool:
        """Revoke at Strava, then forget locally even if revocation fails."""
        tokens = self.store.load()
        revoked = False
        if tokens is not None:
            try:
                http = await self._client()
                response = await http.post(
                    DEAUTHORIZE_URL, data={"access_token": tokens.access_token}
                )
                revoked = response.status_code < 400
            except httpx.HTTPError:
                log.warning("Strava deauthorize call failed; clearing local tokens anyway")
        self.store.clear()
        return revoked

    # -- API calls -------------------------------------------------------

    async def get(
        self, path: str, params: Optional[dict[str, Any]] = None, *, retries: int = 3
    ) -> ProviderResult:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        started = time.perf_counter()
        attempt = 0
        while True:
            try:
                token = await self.access_token()
            except StravaNotConnected as exc:
                return ProviderResult(
                    provider="strava", endpoint=path, params=params,
                    status=ResultStatus.UNSUPPORTED, message=str(exc),
                )
            http = await self._client()
            try:
                response = await http.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                outcome = ProviderResult(
                    provider="strava", endpoint=path, params=params,
                    status=ResultStatus.PROTOCOL_ERROR,
                    message=f"{type(exc).__name__}",
                )
            else:
                self.rate_limit.update(response.headers)
                outcome = self._interpret(path, params, response)
            outcome.duration_ms = int((time.perf_counter() - started) * 1000)
            log.debug(
                "strava request",
                extra={"endpoint": path, "status": outcome.status.value,
                       "duration_ms": outcome.duration_ms, "attempt": attempt},
            )
            if outcome.ok or outcome.status.is_permanent or attempt >= retries:
                return outcome
            attempt += 1
            await asyncio.sleep(self._backoff(outcome.status, attempt))

    def _interpret(
        self, path: str, params: dict[str, Any], response: httpx.Response
    ) -> ProviderResult:
        if response.status_code == 429:
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.RATE_LIMITED,
                message="Strava rate limit reached",
            )
        if response.status_code == 401:
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.ERROR,
                message="Strava rejected the access token (401)",
            )
        if response.status_code == 404:
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.NO_DATA, message="Not found",
            )
        if response.status_code >= 400:
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.ERROR,
                message=f"Strava returned HTTP {response.status_code}",
            )
        try:
            data = response.json()
        except ValueError:
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.ERROR, message="Strava returned non-JSON content",
            )
        if data in (None, [], {}):
            return ProviderResult(
                provider="strava", endpoint=path, params=params,
                status=ResultStatus.NO_DATA, data=data, message="Empty result",
            )
        return ProviderResult(
            provider="strava", endpoint=path, params=params,
            status=ResultStatus.OK, data=data,
        )

    @staticmethod
    def _backoff(status: ResultStatus, attempt: int) -> float:
        base = 60.0 if status is ResultStatus.RATE_LIMITED else 2.0
        return min(base * (2 ** (attempt - 1)), 900.0)

    # -- endpoint helpers ------------------------------------------------

    async def athlete(self) -> ProviderResult:
        return await self.get("/athlete")

    async def athlete_stats(self, athlete_id: str) -> ProviderResult:
        return await self.get(f"/athletes/{athlete_id}/stats")

    async def athlete_zones(self) -> ProviderResult:
        return await self.get("/athlete/zones")

    async def activities_page(
        self, after: Optional[int], before: Optional[int], page: int, per_page: int = 100
    ) -> ProviderResult:
        return await self.get(
            "/athlete/activities",
            {"after": after, "before": before, "page": page, "per_page": per_page},
        )

    async def activity(self, activity_id: str) -> ProviderResult:
        return await self.get(
            f"/activities/{activity_id}", {"include_all_efforts": "true"}
        )

    async def activity_laps(self, activity_id: str) -> ProviderResult:
        return await self.get(f"/activities/{activity_id}/laps")

    async def activity_zones(self, activity_id: str) -> ProviderResult:
        return await self.get(f"/activities/{activity_id}/zones")

    async def activity_streams(self, activity_id: str) -> ProviderResult:
        return await self.get(
            f"/activities/{activity_id}/streams",
            {"keys": ",".join(STREAM_KEYS), "key_by_type": "true"},
        )

    async def gear(self, gear_id: str) -> ProviderResult:
        return await self.get(f"/gear/{gear_id}")

    async def routes(self, athlete_id: str, page: int = 1) -> ProviderResult:
        return await self.get(
            f"/athletes/{athlete_id}/routes", {"page": page, "per_page": 50}
        )
