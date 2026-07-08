"""Shared pytest fixtures (COORDINATION.md §3: owned by testing-evals).

Fixture-mode per COORDINATION.md §4: no `app.agent` import. `FakeLLM`/`FakeAgent`
stand in for the real LlamaIndex agent so tool-unit tests (this feature's own, and
other features' test files once they land under `tests/`) don't need a live OpenAI
call or a live agent loop.

`pytest-asyncio` runs in `asyncio_mode = "auto"` (pyproject.toml) so plain `async def
test_...` functions and async fixtures need no extra markers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from app.contracts import CaseFile, Customer

# --- FakeLLM / FakeAgent ----------------------------------------------------------


class FakeLLM:
    """Minimal scripted stand-in for an LLM client: returns canned replies in order."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies: list[str] = list(replies or [])
        self.prompts: list[str] = []

    async def acomplete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._replies:
            return ""
        return self._replies.pop(0)

    def queue(self, reply: str) -> None:
        self._replies.append(reply)


@dataclass
class FakeAgent:
    """Scripted agent stand-in: a sequential caller-turn -> agent-reply script.

    Not `app.agent.*` — lets a tool-unit test drive a conversation-shaped exchange
    without a live agent loop or an OpenAI call. Mirrors the transcript-runner's
    fixture-mode contract (`role`: "user"/"agent").
    """

    script: list[str] = field(default_factory=list)
    case_file: CaseFile = field(default_factory=CaseFile)
    transcript: list[dict[str, str]] = field(default_factory=list)

    async def chat(self, user_text: str) -> str:
        self.transcript.append({"role": "user", "text": user_text})
        reply = self.script.pop(0) if self.script else "(no scripted reply left)"
        self.transcript.append({"role": "agent", "text": reply})
        return reply


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_agent() -> FakeAgent:
    return FakeAgent()


# --- Factories ---------------------------------------------------------------------


def make_case_file(**overrides: Any) -> CaseFile:
    return CaseFile.model_validate(overrides)


def make_customer(**overrides: Any) -> Customer:
    defaults: dict[str, Any] = {
        "name": "Jordan Rivera",
        "zip": "60614",
        "email": "jordan.rivera@example.com",
    }
    defaults.update(overrides)
    return Customer.model_validate(defaults)


def make_technician_row(**overrides: Any) -> dict[str, Any]:
    """A seeded-technician-shaped dict (schema owned by technician-scheduling,
    Alembic rev `0002_scheduling`) for tests that need a plausible row without a
    live DB."""
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "name": "Alex Chen",
        "phone": "+13125550100",
        "email": "alex.chen@searshometech.example",
        "employment_type": "full_time",
        "hired_on": "2021-03-01",
        "active": True,
        "specialties": ["washer", "dryer"],
        "zip_codes": ["60614", "60647"],
    }
    defaults.update(overrides)
    return defaults


def make_session_row(**overrides: Any) -> dict[str, Any]:
    """A `sessions` row-shaped dict (Alembic rev `0001_core`)."""
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "customer_id": None,
        "channel": "web",
        "appliance_type": None,
        "case_file": {},
        "transcript": [],
        "started_at": None,
        "ended_at": None,
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def technician_factory():
    return make_technician_row


@pytest.fixture
def session_factory():
    return make_session_row


@pytest.fixture
def case_file_factory():
    return make_case_file


@pytest.fixture
def customer_factory():
    return make_customer


# --- DB session (Compose `db`) ------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[Any]:
    """An async SQLAlchemy session against `DATABASE_URL`, rolled back after the test.

    Skips (never fails) when no reachable Postgres is configured: this harness's own
    gate does not require a live DB (COORDINATION.md §4). Feature-owned test files
    that need real tables opt in by requesting this fixture once their models land.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — db_session fixture needs a reachable Postgres")

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    try:
        connection = await engine.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")
        return

    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
