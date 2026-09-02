"""Shared FastAPI dependencies: sessions, settings, and query-parameter parsing."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.session import db_session
from .errors import bad_request

SessionDep = Annotated[Session, Depends(db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

MAX_RANGE_DAYS = 1100


class DateRange:
    """A validated, bounded ``[start, end]`` window used by every series route."""

    def __init__(self, start: date, end: date) -> None:
        self.start = start
        self.end = end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def date_range(
    start: Optional[date] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    days: int = Query(90, ge=1, le=MAX_RANGE_DAYS,
                      description="Window size when start/end are omitted"),
) -> DateRange:
    resolved_end = end or date.today()
    resolved_start = start or (resolved_end - timedelta(days=days - 1))
    if resolved_start > resolved_end:
        raise bad_request("start must be on or before end")
    if (resolved_end - resolved_start).days + 1 > MAX_RANGE_DAYS:
        raise bad_request(f"Date range must not exceed {MAX_RANGE_DAYS} days")
    return DateRange(resolved_start, resolved_end)


DateRangeDep = Annotated[DateRange, Depends(date_range)]


class Pagination:
    def __init__(self, limit: int, offset: int) -> None:
        self.limit = limit
        self.offset = offset


def pagination(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Pagination:
    return Pagination(limit, offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]
