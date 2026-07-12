"""Behavioral alembic tests (bugfix-loop T2).

`docker-entrypoint.sh` runs `alembic upgrade heads` as the first step of the
assignment's single-command Docker promise, yet no test ever *executed* a
migration — `tests/scheduling/test_schema.py` parses the revision graph and
builds tables from SQLAlchemy metadata, so a broken `op.create_table`, a bad
server default, or a merge that loses one branch would ship undetected.

These tests run the real alembic CLI (subprocess — env.py drives an async
engine, so in-process invocation would nest event loops) against a dedicated
`<db>_test_migrations` database on the same server, mirroring the isolation
convention of tests/scheduling/conftest.py. Skips loudly without DATABASE_URL.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import normalize_asyncpg_url

REPO_ROOT = Path(__file__).resolve().parents[1]

# Same .env fallback as tests/scheduling/conftest.py, kept local so this module
# stays standalone (it is not part of that subpackage).
if not os.environ.get("DATABASE_URL"):
    _env = REPO_ROOT / ".env"
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _s = _line.strip()
            if _s and not _s.startswith("#") and "=" in _s:
                _k, _, _v = _s.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

_BASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _BASE_URL,
    reason="SKIPPED (not passed): DATABASE_URL not set — migration tests need a Postgres server",
)

_EXPECTED_TABLES = {
    # 0001 core
    "customers",
    "sessions",
    # 0002 scheduling
    "technicians",
    "technician_specialties",
    "service_areas",
    "availability_slots",
    "appointments",
    # 0003 visual
    "image_uploads",
}


def _test_url() -> str:
    url = make_url(_BASE_URL)
    return url.set(database=f"{url.database}_test_migrations").render_as_string(hide_password=False)


async def _exec_admin(sql: str, **params) -> object:
    admin = create_async_engine(
        normalize_asyncpg_url(
            make_url(_BASE_URL).set(database="postgres").render_as_string(hide_password=False)
        ),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin.connect() as conn:
            result = await conn.execute(text(sql), params)
            return result.scalar() if result.returns_rows else None
    finally:
        await admin.dispose()


@pytest_asyncio.fixture
async def clean_migrations_db() -> str:
    """A dedicated, empty database for one migration run; returns its URL."""
    db_name = make_url(_test_url()).database
    try:
        exists = await _exec_admin("SELECT 1 FROM pg_database WHERE datname = :name", name=db_name)
    except Exception as exc:  # pragma: no cover - environment dependent
        # Skip (never fail) without a reachable Postgres — same policy as the
        # shared db_session fixture in tests/conftest.py.
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")
    if not exists:
        await _exec_admin(f'CREATE DATABASE "{db_name}"')
    engine = create_async_engine(normalize_asyncpg_url(_test_url()))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
    return _test_url()


def _alembic(command: list[str], db_url: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL_DIRECT=db_url, DATABASE_URL=db_url)
    return subprocess.run(
        ["uv", "run", "alembic", *command],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


async def _db_state(db_url: str) -> tuple[set[str], set[str]]:
    """(public table names, alembic_version contents) of the test database."""
    engine = create_async_engine(normalize_asyncpg_url(db_url))
    try:
        async with engine.connect() as conn:
            tables = {
                row[0]
                for row in await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            }
            versions: set[str] = set()
            if "alembic_version" in tables:
                versions = {
                    row[0]
                    for row in await conn.execute(text("SELECT version_num FROM alembic_version"))
                }
            return tables, versions
    finally:
        await engine.dispose()


def _script_heads() -> set[str]:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


async def test_upgrade_heads_builds_the_full_schema_on_an_empty_db(
    clean_migrations_db: str,
) -> None:
    result = _alembic(["upgrade", "heads"], clean_migrations_db)
    assert result.returncode == 0, f"alembic upgrade heads failed:\n{result.stderr[-2000:]}"

    tables, versions = await _db_state(clean_migrations_db)
    missing = _EXPECTED_TABLES - tables
    assert missing == set(), f"tables not created by migrations: {sorted(missing)}"
    assert versions == _script_heads(), "alembic_version does not match the script heads"

    # 0005: sessions.call_sid must exist (the merge chain kept both branches
    # AND the post-merge revision applied).
    engine = create_async_engine(normalize_asyncpg_url(clean_migrations_db))
    try:
        async with engine.connect() as conn:
            call_sid = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'sessions' AND column_name = 'call_sid'"
                    )
                )
            ).scalar()
    finally:
        await engine.dispose()
    assert call_sid, "sessions.call_sid (rev 0005) missing after upgrade heads"


async def test_downgrade_base_round_trips(clean_migrations_db: str) -> None:
    up = _alembic(["upgrade", "heads"], clean_migrations_db)
    assert up.returncode == 0, f"initial upgrade failed:\n{up.stderr[-2000:]}"

    down = _alembic(["downgrade", "base"], clean_migrations_db)
    assert down.returncode == 0, f"alembic downgrade base failed:\n{down.stderr[-2000:]}"
    tables, versions = await _db_state(clean_migrations_db)
    assert tables - {"alembic_version"} == set(), (
        f"downgrade base left tables behind: {sorted(tables - {'alembic_version'})}"
    )
    assert versions == set()

    again = _alembic(["upgrade", "heads"], clean_migrations_db)
    assert again.returncode == 0, f"re-upgrade after downgrade failed:\n{again.stderr[-2000:]}"
    tables, versions = await _db_state(clean_migrations_db)
    assert _EXPECTED_TABLES <= tables
    assert versions == _script_heads()
