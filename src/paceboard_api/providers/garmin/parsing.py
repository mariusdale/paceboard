"""Classify what a Garmin MCP tool actually returned.

The MCP server wraps every tool response in text content. Most tools emit JSON,
but several return a bare sentence instead, and those sentences mean very
different things:

    "No gear found."                                    -> NO_DATA
    "No training readiness data found for 2026-09-01"   -> NO_DATA
    "Your device does not support this metric."         -> UNSUPPORTED
    "Date range too large (61 days). Maximum is 30."    -> INVALID_REQUEST
    "Error retrieving endurance score data: ..."        -> ERROR
    "Garmin rate limit hit. Wait a few minutes..."      -> RATE_LIMITED

Getting this wrong is expensive in both directions: treating "no data" as an
error floods the error log for a metric the watch simply does not record, while
treating an error as "no data" silently drops real information. Classification
is therefore explicit and ordered — the most specific patterns win.

All patterns are matched against the response text only; the sentences above are
provider-generated and contain no personal values, but the classifier never
copies more than a bounded prefix into a log or error record either way.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from ..dto import ResultStatus

MAX_MESSAGE_CHARS = 300

# Ordered most-specific first; the first match decides.
_PATTERNS: tuple[tuple[ResultStatus, re.Pattern[str]], ...] = (
    (
        ResultStatus.RATE_LIMITED,
        re.compile(r"rate limit|too many requests|429", re.I),
    ),
    (
        ResultStatus.TIMEOUT,
        re.compile(r"did not return within|timed out|timeout", re.I),
    ),
    (
        ResultStatus.UNSUPPORTED,
        re.compile(
            r"device does not support|not supported (?:on|by)|no such tool|unknown tool"
            r"|unsupported metric",
            re.I,
        ),
    ),
    (
        ResultStatus.INVALID_REQUEST,
        re.compile(
            r"date range too large|invalid date|must be (?:a |an )?(?:valid|positive)"
            r"|maximum is \d+|expected .* format|invalid \w+ argument",
            re.I,
        ),
    ),
    (
        ResultStatus.ERROR,
        re.compile(
            r"^error\b|error retrieving|error fetching|failed to|authentication expired"
            r"|is unreachable|traceback", re.I,
        ),
    ),
    (
        ResultStatus.NO_DATA,
        re.compile(
            r"^no\s|no data|not found|no measurements|no records|nothing (?:found|recorded)"
            r"|has no data|is empty|no activities", re.I,
        ),
    ),
)


def classify_text(text: str) -> tuple[ResultStatus, str]:
    """Map a plain-text tool response to a status and a bounded message."""
    stripped = (text or "").strip()
    message = stripped[:MAX_MESSAGE_CHARS]
    if not stripped:
        return ResultStatus.NO_DATA, "Empty response"
    for status, pattern in _PATTERNS:
        if pattern.search(stripped):
            return status, message
    # An unrecognised non-JSON sentence is treated as an error rather than
    # silently swallowed: an unknown shape is a signal, not an absence.
    return ResultStatus.ERROR, message


def _is_empty_payload(value: Any) -> bool:
    """True when valid JSON nonetheless carries nothing usable.

    Garmin returns e.g. ``{"date": "2026-08-31"}`` for a day with no SpO2 or
    ``{"start_date": ..., "daily_scores": []}`` for an empty range. Those are
    absences, not failures, and must not be normalized into zeroes.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, dict):
        if not value:
            return True
        meaningful = {
            k: v
            for k, v in value.items()
            if k not in _ECHO_KEYS and v is not None and v != [] and v != {}
        }
        return not meaningful
    return False


# Keys Garmin echoes back from the request; their presence alone proves nothing.
_ECHO_KEYS = frozenset(
    {
        "date",
        "start_date",
        "end_date",
        "startDate",
        "endDate",
        "activity_id",
        "activityId",
        "sport",
        "days_with_data",
        "data_points",
        "nights_requested",
        "nights_returned",
        "weeks_requested",
        "weeks_returned",
        "count",
        "page",
        "page_size",
        "has_more",
        "date_range",
        "source",
    }
)


def parse_tool_text(text: str) -> tuple[ResultStatus, Any, Optional[str]]:
    """Parse one tool's text content into ``(status, data, message)``.

    ``data`` is the decoded JSON when the response was JSON, else ``None``.
    """
    stripped = (text or "").strip()
    if not stripped:
        return ResultStatus.NO_DATA, None, "Empty response"
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return (
                ResultStatus.ERROR,
                None,
                f"Malformed JSON from tool: {exc.msg} at position {exc.pos}",
            )
        if _is_empty_payload(data):
            return ResultStatus.NO_DATA, data, "Provider returned no values for this window"
        return ResultStatus.OK, data, None
    status, message = classify_text(stripped)
    return status, None, message


def extract_text(content: Iterable[Any]) -> str:
    """Concatenate the text parts of an MCP ``CallToolResult.content``."""
    parts: list[str] = []
    for item in content or ():
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)
