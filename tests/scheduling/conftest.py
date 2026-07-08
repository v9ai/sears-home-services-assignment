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
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.db import matching
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


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    await matching.reset_engine()
    engine = matching.get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(SchedulingBase.metadata.create_all)
    yield
    await matching.reset_engine()
