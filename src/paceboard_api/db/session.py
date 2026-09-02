"""Engine + session factory.

SQLite is used in WAL mode with a busy timeout so the background scheduler and
the API can write concurrently without ``database is locked`` errors. The
database file is created with owner-only permissions: it holds personal health
data and must not be world-readable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def secure_database_file(path: Path) -> None:
    """Restrict the database to its owner.

    Called from every path that can create the file — the engine factory *and*
    the Alembic environment. Migrations run through ``engine_from_config`` rather
    than :func:`build_engine`, so without this a fresh ``paceboard-api migrate``
    would leave a file of personal health data world-readable.
    """
    try:
        if path.exists():
            os.chmod(path, 0o600)
        for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            if sidecar.exists():
                os.chmod(sidecar, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass


def _apply_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - driver callback
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    path: Path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    engine = create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    _apply_sqlite_pragmas(engine)
    if not existed:
        # Touch through the engine so the file exists before chmod.
        with engine.connect():
            pass
    secure_database_file(path)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope; commits on success, rolls back on failure."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """Dispose the cached engine/factory (tests point at a temp database)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
