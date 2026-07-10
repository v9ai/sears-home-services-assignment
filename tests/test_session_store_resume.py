"""Resume + persistence coverage for `app/agent/session_store.py` (coverage round 2,
task #24).

The fresh-session path is already exercised elsewhere; these tests pin the previously
uncovered halves — the resume-existing branch of `load_or_create_session`,
`_memory_from_transcript` with a non-empty transcript (role mapping + order), and
`persist_session`'s round trip — which together are what makes "reload the tab
mid-session and the agent resumes without re-asking" work.

DB layer: a dedicated `<db>_test_session_store` Postgres database on the same server as
`DATABASE_URL` (loaded from the repo-root `.env` if unset), with a fresh `public` schema
per test — the same isolation approach as `tests/scheduling/conftest.py`, never touching
the shared app database. Skips loudly (never fails) when no Postgres is reachable.

`get_llm()` is faked so `_memory_from_transcript` needs no API key — no network, no keys.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import session_store
from app.agent.session_store import SessionState
from app.contracts import CaseFile, Customer, Symptom
from app.db.base import normalize_asyncpg_url
from app.db.models_core import Base, SessionRecord
from tests.fakes import FakeFunctionCallingLLM

_TEST_DB_SUFFIX = "_test_session_store"


def _load_dotenv_if_needed() -> None:
    if os.environ.get("DATABASE_URL"):
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _test_db_name(base_url: str) -> str:
    return f"{normalize_asyncpg_url(base_url).database}{_TEST_DB_SUFFIX}"


async def _ensure_test_database(base_url: str, name: str) -> None:
    """Create the isolated tests database if missing. DDL here only ever targets the
    `postgres` maintenance DB or `name` — never the shared app database."""
    admin_url = normalize_asyncpg_url(base_url).set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                )
            ).scalar()
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def session_maker() -> async_sessionmaker:
    """A sessionmaker bound to an isolated, freshly-schema'd tests database.

    Distinct `async with session_maker() as db` blocks stand in for separate WS
    connects, so a persist in one session and a resume in another exercise a real
    committed round trip (not just the identity map)."""
    _load_dotenv_if_needed()
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        pytest.skip("DATABASE_URL not set — session_store resume tests need a reachable Postgres")

    name = _test_db_name(base_url)
    try:
        await _ensure_test_database(base_url, name)
    except Exception as exc:  # pragma: no cover — environment dependent
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")

    engine = create_async_engine(normalize_asyncpg_url(base_url).set(database=name))
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch) -> None:
    # _memory_from_transcript builds a ChatMemoryBuffer via get_llm(); the fake keeps the
    # whole suite keyless (get_llm() would otherwise KeyError without DEEPSEEK_API_KEY).
    monkeypatch.setattr(session_store, "get_llm", lambda: FakeFunctionCallingLLM([]))


# --- _memory_from_transcript (unit, no DB) ---------------------------------------------


def test_memory_from_transcript_maps_roles_and_preserves_order() -> None:
    transcript = [
        {"role": "user", "text": "my washer won't drain"},
        {"role": "agent", "text": "Let's check the drain filter."},
        {"role": "user", "text": "ok, found a sock"},
    ]

    memory = session_store._memory_from_transcript(transcript)

    messages = memory.get_all()
    # agent -> assistant; user stays user; order preserved 1:1 with the transcript.
    assert [("user" if m.role == "user" else "assistant") for m in messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [m.content for m in messages] == [
        "my washer won't drain",
        "Let's check the drain filter.",
        "ok, found a sock",
    ]


def test_memory_from_transcript_empty_yields_empty_memory() -> None:
    assert session_store._memory_from_transcript([]).get_all() == []


# --- load_or_create_session: resume vs fresh -------------------------------------------


async def test_resume_existing_session_is_not_new_and_rebuilds_memory(session_maker) -> None:
    sid = uuid.uuid4()
    case = CaseFile(
        appliance_type="washer",
        brand="Kenmore",
        customer=Customer(name="Jordan", zip="60614"),
    )
    transcript = [
        {"role": "user", "text": "washer is loud"},
        {"role": "agent", "text": "Since when?"},
        {"role": "user", "text": "yesterday"},
    ]
    async with session_maker() as db:
        db.add(
            SessionRecord(
                id=sid,
                channel="web",
                case_file=case.model_dump(mode="json"),
                appliance_type="washer",
                transcript=transcript,
            )
        )
        await db.commit()

    async with session_maker() as db:
        state = await session_store.load_or_create_session(db, str(sid))

    assert state.is_new is False
    assert state.session_id == sid
    assert state.case_file.appliance_type == "washer"
    assert state.case_file.brand == "Kenmore"
    assert state.case_file.customer.zip == "60614"
    assert state.transcript == transcript
    # Memory rebuilt from the persisted transcript, roles/order preserved.
    messages = state.memory.get_all()
    assert [("user" if m.role == "user" else "assistant") for m in messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [m.content for m in messages] == ["washer is loud", "Since when?", "yesterday"]


async def test_unknown_session_id_creates_fresh_honoring_the_client_id(session_maker) -> None:
    sid = uuid.uuid4()  # a valid id the DB has never seen

    async with session_maker() as db:
        state = await session_store.load_or_create_session(db, str(sid))

    assert state.is_new is True
    assert state.session_id == sid  # client-supplied id is honored, not regenerated
    assert state.transcript == []
    assert state.case_file == CaseFile()
    # The fresh branch commits a row so the next connect resumes it.
    async with session_maker() as db:
        record = await db.get(SessionRecord, sid)
        assert record is not None
        assert record.channel == "web"


async def test_none_session_id_creates_fresh_with_random_id(session_maker) -> None:
    async with session_maker() as db:
        state = await session_store.load_or_create_session(db, None)

    assert state.is_new is True
    assert isinstance(state.session_id, uuid.UUID)


# --- persist_session round trips -------------------------------------------------------


async def test_persist_round_trips_case_file_and_transcript(session_maker) -> None:
    sid = uuid.uuid4()
    async with session_maker() as db:
        state = await session_store.load_or_create_session(db, str(sid))

    # Mutate the way a turn would, then persist.
    state.case_file.appliance_type = "dryer"
    state.case_file.brand = "Whirlpool"
    state.case_file.customer.zip = "60647"
    state.case_file.symptoms.append(Symptom(description="no heat", onset="today"))
    state.transcript = [
        {"role": "user", "text": "dryer no heat"},
        {"role": "agent", "text": "Got it — let's check the thermal fuse."},
    ]
    async with session_maker() as db:
        await session_store.persist_session(db, state)

    async with session_maker() as db:
        resumed = await session_store.load_or_create_session(db, str(sid))

    assert resumed.is_new is False
    assert resumed.case_file.appliance_type == "dryer"
    assert resumed.case_file.brand == "Whirlpool"
    assert resumed.case_file.customer.zip == "60647"
    assert [s.description for s in resumed.case_file.symptoms] == ["no heat"]
    assert resumed.transcript == state.transcript
    # The denormalized appliance_type column is mirrored for the sessions listing.
    async with session_maker() as db:
        record = await db.get(SessionRecord, sid)
        assert record.appliance_type == "dryer"


async def test_persist_creates_the_row_when_absent(session_maker) -> None:
    # persist_session is called for a session_id with no pre-existing row (lines 86-88).
    sid = uuid.uuid4()
    state = SessionState(
        session_id=sid,
        case_file=CaseFile(appliance_type="oven"),
        memory=session_store._memory_from_transcript([]),
        transcript=[{"role": "user", "text": "oven won't heat"}],
    )

    async with session_maker() as db:
        await session_store.persist_session(db, state)

    async with session_maker() as db:
        record = await db.get(SessionRecord, sid)
    assert record is not None
    assert record.case_file["appliance_type"] == "oven"
    assert record.transcript == [{"role": "user", "text": "oven won't heat"}]


async def test_persist_then_resume_yields_identical_case_file(session_maker) -> None:
    # The booking-state pin (interacts with #21): a resumed session keeps its zip,
    # appliance, brand and symptoms across a reconnect, byte-for-byte.
    sid = uuid.uuid4()
    original = CaseFile(
        appliance_type="washer",
        brand="Kenmore",
        model="665.13743K310",
        customer=Customer(name="Jordan Rivera", zip="60614", email="jordan@example.com"),
        symptoms=[Symptom(description="loud grinding", onset="3 days ago", sound="grinding")],
        steps_given=["checked drum for foreign objects"],
        safety_flag=False,
    )
    state = SessionState(
        session_id=sid,
        case_file=original,
        memory=session_store._memory_from_transcript([]),
        transcript=[{"role": "user", "text": "hi"}],
    )
    async with session_maker() as db:
        await session_store.persist_session(db, state)

    async with session_maker() as db:
        resumed = await session_store.load_or_create_session(db, str(sid))

    assert resumed.case_file.model_dump() == original.model_dump()
    assert resumed.case_file.customer.zip == "60614"  # zip survives the reconnect


# --- malformed session_id degrades to a fresh session (task #26, fixed) ----------------


async def test_malformed_session_id_degrades_to_fresh_session(session_maker) -> None:
    # A garbage ?session_id query param must not 500 the /ws/call connect — the fresh
    # branch reuses the already-None parsed_id rather than re-parsing (task #26 fix).
    async with session_maker() as db:
        state = await session_store.load_or_create_session(db, "not-a-uuid")

    assert state.is_new is True
    assert isinstance(state.session_id, uuid.UUID)
