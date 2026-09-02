"""Small upsert helpers shared by every normalizer.

Idempotency is the point: a sync repeated over the same window must update rows
in place, never append. Each helper looks the row up by its natural key, creates
it if absent, and then applies only the fields the provider actually supplied —
``None`` never overwrites a value another source already established.
"""

from __future__ import annotations

from typing import Any, Optional, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Base

M = TypeVar("M", bound=Base)


def apply_fields(row: Any, values: dict[str, Any], *, overwrite_none: bool = False) -> int:
    """Copy ``values`` onto ``row``; returns the number of fields that changed."""
    changed = 0
    for key, value in values.items():
        if value is None and not overwrite_none:
            continue
        if getattr(row, key, None) != value:
            setattr(row, key, value)
            changed += 1
    return changed


def get_or_create(
    session: Session, model: Type[M], keys: dict[str, Any], defaults: Optional[dict[str, Any]] = None
) -> tuple[M, bool]:
    stmt = select(model)
    for key, value in keys.items():
        stmt = stmt.where(getattr(model, key) == value)
    row = session.execute(stmt).scalar_one_or_none()
    if row is not None:
        return row, False
    row = model(**keys, **(defaults or {}))
    session.add(row)
    session.flush()
    return row, True


def upsert(
    session: Session,
    model: Type[M],
    keys: dict[str, Any],
    values: dict[str, Any],
    *,
    raw_payload_id: Optional[int] = None,
) -> M:
    row, _created = get_or_create(session, model, keys)
    apply_fields(row, values)
    if raw_payload_id is not None and hasattr(row, "raw_payload_id"):
        row.raw_payload_id = raw_payload_id
    session.flush()
    return row
