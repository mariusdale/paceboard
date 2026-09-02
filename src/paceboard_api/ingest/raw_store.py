"""Persist verbatim provider responses.

Every provider call — success, "no data", or error — is stored. Keeping the
failures matters as much as the successes: the Data Explorer's coverage view is
only honest if a metric that returned nothing is visibly recorded as such rather
than simply missing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import RawPayload
from ..providers.dto import ProviderResult

SCHEMA_VERSION = "1"

#: Endpoints whose response body is deliberately not retained verbatim.
#:
#: A single FIT record page is a few megabytes of JSON, and Paceboard already
#: keeps every one of those samples in ``activity_streams``, zlib-compressed and
#: queryable. Storing the same samples a second time as raw JSON would grow the
#: database by hundreds of megabytes a year to duplicate data that is already
#: preserved. The provenance row is still written — endpoint, parameters, status,
#: true byte size, duration, retrieval time — and its stored text says where the
#: samples actually live, so the Data Explorer never shows an unexplained gap.
BODY_NOT_RETAINED: frozenset[str] = frozenset({
    "get_activity_fit_messages",
    "get_activity_fit_data",
})

_OMITTED_NOTE = (
    "Body not retained: this endpoint returns per-sample FIT records, which "
    "Paceboard stores compressed in activity_streams instead of duplicating "
    "here. Endpoint, parameters, status, size and timing are preserved above."
)


def params_hash(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def store_result(
    session: Session,
    result: ProviderResult,
    *,
    sync_run_id: Optional[int] = None,
    reference_kind: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> RawPayload:
    """Upsert one provider response keyed by (provider, endpoint, params)."""
    digest = params_hash(result.params)
    row = session.execute(
        select(RawPayload).where(
            RawPayload.provider == result.provider,
            RawPayload.endpoint == result.endpoint,
            RawPayload.params_hash == digest,
        )
    ).scalar_one_or_none()

    body = result.data if result.data is not None else result.text
    serialized = json.dumps(body, default=str) if body is not None else ""
    # Successful bulk-sample responses keep their provenance but not their body.
    omit_body = result.endpoint in BODY_NOT_RETAINED and result.ok

    if row is None:
        row = RawPayload(
            provider=result.provider,
            endpoint=result.endpoint,
            params_hash=digest,
        )
        session.add(row)

    row.params = result.params
    row.schema_version = SCHEMA_VERSION
    row.status = result.status.value
    if omit_body:
        row.content_type = "omitted"
        row.content_json = None
        row.content_text = _OMITTED_NOTE
    else:
        row.content_type = result.content_type
        row.content_json = result.data
        row.content_text = result.text if result.data is None else None
    # The true size of what the provider sent, whether or not it was retained.
    row.byte_size = len(serialized)
    row.duration_ms = result.duration_ms
    row.retrieved_at = result.retrieved_at or datetime.utcnow()
    row.sync_run_id = sync_run_id
    if reference_kind:
        row.reference_kind = reference_kind
        row.reference_id = reference_id
    session.flush()
    return row
