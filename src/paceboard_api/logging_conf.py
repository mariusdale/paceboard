"""Structured logging that never emits provider payloads or secrets.

Log records carry short, typed context (tool name, argument *keys*, duration,
status). Response bodies and credential-bearing values never reach a handler:
:class:`RedactingFilter` scrubs anything that looks like a token even when a
third-party library logs it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(?i)(access_token|refresh_token|client_secret|authorization|bearer|code|api[_-]?key)"
               r"\"?\s*[:=]\s*\"?([A-Za-z0-9._\-]{6,})"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{6,}"),
]

_STANDARD = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: _mask(m.group(0)), text)
    return text


def _mask(fragment: str) -> str:
    head, sep, _ = fragment.partition("=") if "=" in fragment else fragment.partition(":")
    return f"{head}{sep or ' '}<redacted>" if sep else "<redacted>"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            ) if isinstance(record.args, tuple) else record.args
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool, type(None))):
                payload[key] = value
            else:
                payload[key] = str(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)[-2000:]
        return redact(json.dumps(payload, default=str))


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactingFilter())
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s", "%H:%M:%S")
        )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for noisy in ("httpx", "httpcore", "apscheduler.executors.default", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
