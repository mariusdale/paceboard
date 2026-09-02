"""Migrations must build the exact schema the models expect, from empty."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from paceboard_api.config import REPO_ROOT
from paceboard_api.db.models import Base


def run_alembic(command: list[str], database_path: Path) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "PACEBOARD_DATABASE_PATH": str(database_path)}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )


@pytest.fixture()
def migrated(tmp_path) -> Path:
    database = tmp_path / "migrated.sqlite3"
    result = run_alembic(["upgrade", "head"], database)
    assert result.returncode == 0, result.stderr
    assert database.exists()
    return database


class TestUpgradeFromEmpty:
    def test_every_model_table_is_created(self, migrated):
        engine = create_engine(f"sqlite+pysqlite:///{migrated}")
        tables = set(inspect(engine).get_table_names())
        expected = set(Base.metadata.tables)
        assert expected <= tables, f"missing tables: {sorted(expected - tables)}"
        engine.dispose()

    def test_the_schema_matches_the_models_column_for_column(self, migrated):
        engine = create_engine(f"sqlite+pysqlite:///{migrated}")
        inspector = inspect(engine)
        for name, table in Base.metadata.tables.items():
            actual = {column["name"] for column in inspector.get_columns(name)}
            expected = {column.name for column in table.columns}
            assert expected == actual, f"{name}: {expected ^ actual}"
        engine.dispose()

    def test_indexes_the_query_paths_rely_on_exist(self, migrated):
        engine = create_engine(f"sqlite+pysqlite:///{migrated}")
        inspector = inspect(engine)
        indexed = {
            index["name"]
            for table in Base.metadata.tables
            for index in inspector.get_indexes(table)
        }
        for required in ("ix_activities_start", "ix_activities_sport",
                         "ix_daily_health_day", "ix_raw_payload_retrieved",
                         "ix_source_record_start"):
            assert required in indexed
        engine.dispose()

    def test_natural_keys_are_unique_so_upserts_stay_idempotent(self, migrated):
        engine = create_engine(f"sqlite+pysqlite:///{migrated}")
        inspector = inspect(engine)
        constraints = {
            (table, constraint["name"])
            for table in Base.metadata.tables
            for constraint in inspector.get_unique_constraints(table)
        }
        names = {name for _table, name in constraints}
        for required in ("uq_daily_health", "uq_sleep_day", "uq_source_record",
                         "uq_raw_payload", "uq_performance_metric"):
            assert required in names
        engine.dispose()


class TestRepeatability:
    def test_upgrading_an_already_migrated_database_is_a_no_op(self, migrated):
        result = run_alembic(["upgrade", "head"], migrated)
        assert result.returncode == 0, result.stderr

    def test_no_pending_model_changes_remain(self, migrated):
        """A drift check: autogenerate must find nothing left to do."""
        result = run_alembic(["check"], migrated)
        assert result.returncode == 0, (
            "The models have drifted from the migrations. Run:\n"
            "  uv run --extra paceboard alembic revision --autogenerate -m '...'\n\n"
            + result.stdout + result.stderr
        )


class TestCliMigrate:
    def test_the_cli_creates_the_database_and_its_parent_directory(self, tmp_path):
        import os

        target = tmp_path / "nested" / "dir" / "paceboard.sqlite3"
        env = {**os.environ, "PACEBOARD_DATABASE_PATH": str(target)}
        result = subprocess.run(
            [sys.executable, "-m", "paceboard_api.cli", "migrate"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stderr
        assert target.exists()

    def test_a_migrated_database_is_owner_only(self, migrated):
        """The migrate path creates the file itself; it must lock it down too."""
        assert oct(migrated.stat().st_mode)[-3:] == "600"

    def test_the_database_file_is_owner_only(self, tmp_path):
        import os

        from paceboard_api.config import build_settings
        from paceboard_api.db.session import build_engine

        target = tmp_path / "perms.sqlite3"
        os.environ["PACEBOARD_DATABASE_PATH"] = str(target)
        try:
            engine = build_engine(build_settings())
            assert oct(target.stat().st_mode)[-3:] == "600"
            engine.dispose()
        finally:
            os.environ.pop("PACEBOARD_DATABASE_PATH", None)
