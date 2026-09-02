"""Encrypted-at-rest storage for Strava OAuth tokens.

Tokens are sealed with Fernet (AES-128-CBC + HMAC) using a key generated on
first use and written to :attr:`Settings.secret_key_path` with mode ``0600``.
The key sits next to the token file, so this protects against casual disclosure
(a backup, a synced folder, a shoulder-surfed ``cat``) rather than against an
attacker who already has your user account — which is the honest guarantee for
a local-first app with no external key service. That limitation is stated in the
README rather than papered over.

Tokens never leave the backend: no route returns ``access_token`` and no log
line contains one.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ...logging_conf import get_logger

log = get_logger("paceboard.strava.tokens")


@dataclass(slots=True)
class StravaTokens:
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str = ""
    athlete_id: str = ""
    athlete_name: str = ""

    @property
    def expires_at_dt(self) -> datetime:
        return datetime.fromtimestamp(self.expires_at, tz=timezone.utc)

    def is_expired(self, leeway_seconds: int = 300) -> bool:
        now = datetime.now(tz=timezone.utc).timestamp()
        return self.expires_at - leeway_seconds <= now

    def public_view(self) -> dict[str, Any]:
        """Safe to serialize to the browser — no token material."""
        return {
            "athlete_id": self.athlete_id,
            "athlete_name": self.athlete_name,
            "scope": self.scope,
            "expires_at": self.expires_at_dt.isoformat(),
            "expired": self.is_expired(0),
        }


class TokenStore:
    """Loads/saves a single Strava token set, encrypted when possible."""

    def __init__(self, token_path: Path, key_path: Path) -> None:
        self.token_path = token_path
        self.key_path = key_path
        self._cache: Optional[StravaTokens] = None
        self._loaded = False

    # -- crypto ----------------------------------------------------------

    def _fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError:  # pragma: no cover - cryptography is a hard dep
            log.warning(
                "cryptography unavailable; Strava tokens will be stored as "
                "owner-readable plaintext"
            )
            return None
        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(Fernet.generate_key())
            os.chmod(self.key_path, 0o600)
        return Fernet(self.key_path.read_bytes())

    # -- io --------------------------------------------------------------

    def load(self) -> Optional[StravaTokens]:
        if self._loaded:
            return self._cache
        self._loaded = True
        if not self.token_path.exists():
            return None
        blob = self.token_path.read_bytes()
        payload: Optional[dict[str, Any]] = None
        fernet = self._fernet()
        if fernet is not None:
            try:
                payload = json.loads(fernet.decrypt(blob))
            except Exception:
                payload = None
        if payload is None:
            # Tolerate a plaintext file written before a key existed.
            try:
                payload = json.loads(blob)
            except Exception:
                log.error("Strava token file is unreadable; treating as disconnected")
                return None
        try:
            self._cache = StravaTokens(**payload)
        except TypeError:
            log.error("Strava token file has an unexpected shape; ignoring")
            return None
        return self._cache

    def save(self, tokens: StravaTokens) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(asdict(tokens)).encode()
        fernet = self._fernet()
        blob = fernet.encrypt(raw) if fernet is not None else raw
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.chmod(tmp, 0o600)
        tmp.replace(self.token_path)
        os.chmod(self.token_path, 0o600)
        self._cache = tokens
        self._loaded = True
        log.info("Stored Strava tokens", extra={"athlete_id": tokens.athlete_id})

    def clear(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()
        self._cache = None
        self._loaded = True
        log.info("Cleared Strava tokens")

    @property
    def encrypted(self) -> bool:
        return self.key_path.exists()
