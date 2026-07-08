"""Fixtures for the technician-scheduling feature's own verification tests.

Not the shared harness (``tests/conftest.py`` is owned by testing-evals per
COORDINATION.md §3 and is left untouched) — this subpackage is this feature's
stub-seam verification per COORDINATION.md §4: "tools + schema are pure
Python/SQL against contracts.CaseFile; test via pytest with a Compose db... no
live agent required." Requires a reachable Postgres at ``DATABASE_URL`` (falls
back to reading the repo-root ``.env`` if the variable isn't already exported).

Each test gets a fully fresh ``public`` schema: this feature's own tables (via
``models_scheduling.Base.metadata``) plus minimal stand-ins for the
``customers`` / ``sessions`` tables owned by voice-diagnostic-core's rev 0001
(same shape as that feature's requirements.md — needed only so this feature's
``appointments`` FK / the customer-mirror lookup in ``scheduling_tools.py``
have something to reference; those two tables are not this feature's schema).

That fresh schema lives in a dedicated ``<db>_test_scheduling`` database on the
same Postgres server, never in the shared app database named by
``DATABASE_URL`` — the previous version of this fixture ran ``DROP SCHEMA
public CASCADE`` directly against the shared DB, which permanently destroyed
any other feature's tables (migrated schema, seed data) for the rest of the
``pytest`` process once this subpackage's tests ran.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import matching
from app.db.base import normalize_asyncpg_url
from app.db.models_scheduling import Base as SchedulingBase

# Minimal stand-ins for the `customers` / `sessions` tables owned by
# voice-diagnostic-core's rev 0001, registered on *this* Base's MetaData so
# `create_all` can resolve `appointments.session_id` / `customer_id`'s
# string-form ForeignKey targets (SQLAlchemy resolves those by table-name
# lookup within the same MetaData collection). Not this feature's schema —
# just enough shape (per that feature's requirements.md) for FK-safe DDL in
# an isolated test schema.
sa.Table(
    "customers",
    SchedulingBase.metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("name", sa.String(120)),
    sa.Column("phone", sa.String(20)),
    sa.Column("email", sa.String(255)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    extend_existing=True,
)
sa.Table(
    "sessions",
    SchedulingBase.metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("customer_id", PGUUID(as_uuid=True), sa.ForeignKey("customers.id")),
    extend_existing=True,
)


def _load_dotenv_if_needed() -> None:
    if os.environ.get("DATABASE_URL"):
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv_if_needed()

_TEST_DB_SUFFIX = "_test_scheduling"


def _test_database_name(base_url: str) -> str:
    return f"{make_url(base_url).database}{_TEST_DB_SUFFIX}"


def _with_database(base_url: str, database: str) -> str:
    # `str(URL)`/`repr(URL)` mask the password as `***` for safe logging — need the
    # real credentials here since this string becomes the next connection's DSN.
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


async def _ensure_test_database(base_url: str, test_db_name: str) -> None:
    """Create the dedicated scheduling-tests database on the same server if missing.

    DDL here only ever targets the `postgres` maintenance database or the
    isolated `test_db_name` — never the shared app database `base_url` points at.
    """
    admin_engine = create_async_engine(
        normalize_asyncpg_url(_with_database(base_url, "postgres")),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": test_db_name},
                )
            ).scalar()
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        yield
        return

    test_db_name = _test_database_name(base_url)
    test_url = _with_database(base_url, test_db_name)
    os.environ["DATABASE_URL"] = test_url
    try:
        await _ensure_test_database(base_url, test_db_name)
        await matching.reset_engine()
        engine = matching.get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(SchedulingBase.metadata.create_all)
        yield
    finally:
        await matching.reset_engine()
        os.environ["DATABASE_URL"] = base_url
        await matching.reset_engine()
