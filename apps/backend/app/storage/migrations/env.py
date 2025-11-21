# apps/backend/app/storage/migrations/env.py
from __future__ import annotations
from logging.config import fileConfig
from typing import Any, Dict, cast
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Load app settings & metadata ---
from app.configs.settings import get_settings
from app.storage.db import Base
import app.storage.models  # noqa: F401  # ensure models are imported so Base.metadata is populated

from pathlib import Path
from sqlalchemy.engine.url import make_url


# Alembic config
config = context.config
settings = get_settings()

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata

def _normalize_sqlite_url(url_str: str) -> str:
    """
    If the DB URL is SQLite and uses a relative path, rewrite it to an absolute
    path rooted at apps/backend, and ensure the directory exists.
    """
    try:
        url = make_url(url_str)
    except Exception:
        # If URL parsing fails, just return as-is.
        return url_str

    # Handle sqlite and sqlite+aiosqlite
    if not url.drivername.split("+", 1)[0] == "sqlite":
        return url_str

    db_path = url.database or ""
    if not db_path:
        return url_str

    # Resolve backend root: env.py is .../apps/backend/app/storage/migrations/env.py
    # parents[3] -> .../apps/backend
    backend_root = Path(__file__).resolve().parents[3]

    # If relative, make absolute under backend root
    abs_db = Path(db_path)
    if not abs_db.is_absolute():
        abs_db = (backend_root / db_path).resolve()

    # Ensure parent dir exists
    abs_db.parent.mkdir(parents=True, exist_ok=True)

    # Replace database path in URL
    new_url = url.set(database=str(abs_db))
    return str(new_url)

def _resolve_db_url() -> str:
    """Prefer env, then app settings, then alembic.ini. Always return a str."""
    url = (
        os.getenv("DATABASE_URL")
        or getattr(settings, "DATABASE_URL", None)
        or getattr(settings, "DB_DSN", None)
        or config.get_main_option("sqlalchemy.url")
    )
    if not url:
        raise RuntimeError(
            "No database URL configured. "
            "Set DATABASE_URL or define sqlalchemy.url in alembic.ini."
        )
    # NEW: normalize sqlite relative paths to absolute and ensure dir exists
    return _normalize_sqlite_url(str(url))


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = _resolve_db_url()
    config.set_main_option("sqlalchemy.url", url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    url = _resolve_db_url()
    config.set_main_option("sqlalchemy.url", url)
    section: Dict[str, Any] = cast(
        Dict[str, Any],
        config.get_section(config.config_ini_section) or {}
    )
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=(connection.dialect.name == "sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
