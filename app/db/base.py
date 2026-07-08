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

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the project."""


def normalize_asyncpg_url(url: str) -> URL:
    """Rewrite a libpq-style ``DATABASE_URL`` for the asyncpg dialect.

    Neon's dashboard strings carry ``?sslmode=require&channel_binding=require`` —
    libpq parameters asyncpg rejects at connect() time. Translate ``sslmode`` to
    asyncpg's ``ssl`` and drop ``channel_binding`` (asyncpg negotiates it itself).
    """
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    parsed = make_url(url)
    query = dict(parsed.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode is not None and "ssl" not in query:
        query["ssl"] = sslmode
    return parsed.set(query=query)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Lazily build (and cache) the app's async engine from ``DATABASE_URL``."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set (see .env.example).")
    return create_async_engine(normalize_asyncpg_url(url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-dependency-shaped session provider; also usable as a plain `async with`."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
