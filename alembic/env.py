"""Alembic environment — async engine over ``DATABASE_URL_DIRECT``.

Migrations use the *direct* connection string (not the pooled one) per tech-stack.md.
Revision files are hand-written by each owning feature (0001_core / 0002_scheduling /
0003_visual); ``target_metadata`` stays ``None`` here so this shared env file need not
import any feature's models.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

target_metadata = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL_DIRECT") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL_DIRECT (or DATABASE_URL) must be set for Alembic.")
    # Shared normalization: asyncpg driver + libpq TLS param translation (Neon
    # dashboard strings carry sslmode/channel_binding, which asyncpg rejects).
    from app.db.base import normalize_asyncpg_url

    return normalize_asyncpg_url(url).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
