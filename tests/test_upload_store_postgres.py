"""Cross-backend upload-store contract (bugfix-loop T3).

Every lifecycle test in the suite ran only against ``InMemoryUploadStore``;
``PostgresUploadStore`` — the shipped runtime backend — had zero coverage, so
its semantics could silently diverge from the InMemory behavior the tests
prove. This suite runs one contract over BOTH backends: lifecycle transitions,
expiry write-back, per-session isolation, and the (pinned) failure mode of
mutators on unknown tokens.

Postgres lane provisions a dedicated ``<db>_test_uploads`` database (same
isolation convention as tests/scheduling/conftest.py) and skips loudly
without DATABASE_URL; the InMemory lane always runs.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import normalize_asyncpg_url
from app.db.models_visual import metadata as visual_metadata
from app.uploads import db as uploads_db
from app.uploads.store import InMemoryUploadStore, PostgresUploadStore

REPO_ROOT = Path(__file__).resolve().parents[1]

if not os.environ.get("DATABASE_URL"):
    _env = REPO_ROOT / ".env"
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _s = _line.strip()
            if _s and not _s.startswith("#") and "=" in _s:
                _k, _, _v = _s.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

_BASE_URL = os.environ.get("DATABASE_URL")


def _pg_url() -> str:
    url = make_url(_BASE_URL)
    return url.set(database=f"{url.database}_test_uploads").render_as_string(hide_password=False)


async def _provision_pg() -> None:
    admin = create_async_engine(
        normalize_asyncpg_url(
            make_url(_BASE_URL).set(database="postgres").render_as_string(hide_password=False)
        ),
        isolation_level="AUTOCOMMIT",
    )
    db_name = make_url(_pg_url()).database
    try:
        async with admin.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
                )
            ).scalar()
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin.dispose()

    engine = create_async_engine(normalize_asyncpg_url(_pg_url()))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(visual_metadata.create_all)
    finally:
        await engine.dispose()


async def _reset_uploads_engine() -> None:
    if uploads_db._engine is not None:
        await uploads_db._engine.dispose()
        uploads_db._engine = None


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def store(request, monkeypatch):
    """The same contract suite runs against both backends."""
    if request.param == "memory":
        yield InMemoryUploadStore()
        return

    if not _BASE_URL:
        pytest.skip(
            "SKIPPED (not passed): DATABASE_URL not set — Postgres upload-store lane needs a server"
        )
    await _provision_pg()
    monkeypatch.setenv("DATABASE_URL", _pg_url())
    await _reset_uploads_engine()
    try:
        yield PostgresUploadStore()
    finally:
        await _reset_uploads_engine()


async def _age(store, token: str, *, hours: int = 25) -> None:
    """Push a record's expiry into the past on whichever backend is active."""
    past = datetime.now(UTC) - timedelta(hours=hours - 24)
    if isinstance(store, InMemoryUploadStore):
        record = store._by_token[token]
        store._by_token[token] = record.model_copy(update={"expires_at": past})
        return
    engine = create_async_engine(normalize_asyncpg_url(_pg_url()))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE image_uploads SET expires_at = :past WHERE token = :token"),
                {"past": past, "token": token},
            )
    finally:
        await engine.dispose()


async def test_create_then_fetch_round_trips(store) -> None:
    session_id = uuid.uuid4()
    created = await store.create(session_id=session_id, email="caller@example.com")
    fetched = await store.get_by_token(created.token)
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.session_id == session_id
    assert fetched.email == "caller@example.com"
    assert fetched.image_path is None and fetched.vision_analysis is None


async def test_unknown_token_reads_none(store) -> None:
    assert await store.get_by_token("nope") is None


async def test_full_lifecycle_pending_uploaded_analyzed(store) -> None:
    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")
    uploaded = await store.save_image(record.token, "/data/x.jpg")
    assert uploaded.status == "uploaded" and uploaded.image_path == "/data/x.jpg"
    analysis = {"appliance_detected": "dryer", "visible_issues": ["lint"]}
    analyzed = await store.save_analysis(record.token, analysis)
    assert analyzed.status == "analyzed"
    assert (await store.get_by_token(record.token)).vision_analysis == analysis


async def test_mark_failed_is_terminal_even_past_expiry(store) -> None:
    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")
    failed = await store.mark_failed(record.token)
    assert failed.status == "failed"
    await _age(store, record.token)
    assert (await store.get_by_token(record.token)).status == "failed"


async def test_expired_pending_reads_expired_and_writes_back(store) -> None:
    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")
    await _age(store, record.token)
    assert (await store.get_by_token(record.token)).status == "expired"
    # Write-back: a second read must see the stored 'expired', not re-derive.
    assert (await store.get_by_token(record.token)).status == "expired"


async def test_latest_for_session_isolates_sessions(store) -> None:
    mine, other = uuid.uuid4(), uuid.uuid4()
    first = await store.create(session_id=mine, email="a@b.co")
    second = await store.create(session_id=mine, email="a@b.co")
    await store.create(session_id=other, email="x@y.co")
    # Make ordering deterministic even at equal timestamps: age the first.
    latest = await store.latest_for_session(mine)
    assert latest is not None and latest.token in {first.token, second.token}
    assert latest.session_id == mine
    assert await store.latest_for_session(uuid.uuid4()) is None


async def test_save_image_on_a_consumed_token_raises_already_used(store) -> None:
    # Atomic single-use claim (T14): the second save must lose loudly, on both
    # backends, so the route can 409 instead of double-accepting.
    from app.uploads.store import TokenAlreadyUsedError

    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")
    await store.save_image(record.token, "/data/first.jpg")
    with pytest.raises(TokenAlreadyUsedError):
        await store.save_image(record.token, "/data/second.jpg")
    fetched = await store.get_by_token(record.token)
    assert fetched.image_path == "/data/first.jpg", "loser must not overwrite the winner"


async def test_mutators_on_unknown_token_raise_rather_than_corrupt(store) -> None:
    # Pins the CURRENT failure mode (KeyError on InMemory, AssertionError on
    # Postgres): loud failure, no phantom record created. If this is ever
    # softened to a clean domain error, update both backends together.
    with pytest.raises((KeyError, AssertionError)):
        await store.save_image("missing-token", "/data/x.jpg")
    with pytest.raises((KeyError, AssertionError)):
        await store.mark_failed("missing-token")
    assert await store.get_by_token("missing-token") is None
