"""Shared SQLAlchemy declarative base and async engine/session plumbing.

Owned by voice-diagnostic-core (COORDINATION.md §3, `app/db/models_core.py` row) but
this module (`app/db/base.py`) is the common engine/session factory every DB-touching
feature imports — it has no feature-specific models, only the ``Base`` class and the
async session helpers, so all owners import it without editing it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the project."""


def _normalize_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Lazily build (and cache) the app's async engine from ``DATABASE_URL``."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set (see .env.example).")
    return create_async_engine(_normalize_asyncpg_url(url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-dependency-shaped session provider; also usable as a plain `async with`."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
