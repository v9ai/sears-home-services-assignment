"""Async engine/session helper for the visual-diagnosis feature.

Self-contained (no shared ``app/db/session.py`` exists in the foundation scaffold);
lazily builds one asyncpg engine from ``DATABASE_URL``. Kept inside ``app/uploads/``
(an owned path) so no shared file needs editing.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

_engine: AsyncEngine | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set.")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(_database_url(), pool_pre_ping=True)
    return _engine


@asynccontextmanager
async def connect() -> AsyncIterator[AsyncConnection]:
    engine = get_engine()
    async with engine.begin() as conn:
        yield conn
