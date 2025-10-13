# apps/backend/app/storage/migrations/env.py
from __future__ import annotations
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Load app settings & metadata ---
# If you ever run alembic from outside apps/backend, uncomment the sys.path shim below.
# import sys, pathlib
# sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> apps/backend

from app.configs.settings import get_settings
from app.storage.db import Base
import app.storage.models  # noqa: F401  # ensure models are imported so Base.metadata is populated

# Alembic config
config = context.config
settings = get_settings()

# Ensure the URL comes from your app settings (DB_DSN in .env)
config.set_main_option("sqlalchemy.url", settings.DB_DSN)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    context.configure(
        url=settings.DB_DSN,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # detect column type changes
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Helpful for SQLite ALTER TABLE limitations; harmless on Postgres
            render_as_batch=(connection.dialect.name == "sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
