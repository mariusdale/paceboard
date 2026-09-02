"""Alembic environment.

The URL comes from Paceboard's own settings rather than ``alembic.ini`` so that
migrations always target the same database the app uses, and so no connection
string lives in a committed file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from paceboard_api.config import get_settings
from paceboard_api.db.models import Base
from paceboard_api.db.session import secure_database_file

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Alembic creates the file on first connect, bypassing build_engine's
    # permission handling; lock it down before and after running migrations.
    secure_database_file(settings.database_path)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rewrites the
            # table instead, which keeps future migrations workable.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    secure_database_file(settings.database_path)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
