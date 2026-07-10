"""`persist_voice_session` (app/voice/recording.py) — the end-of-call upsert that makes a
phone call show up in `GET /api/recordings`.

It writes the `sessions` row keyed on the deterministic `uuid5(call_sid)` PK: channel
`"phone"`, the call sid, the case file (+ its appliance_type), the transcript derived from
the pipeline's LLMContext, and the started/ended timestamps. Hermetic — a fake async
session factory stands in for Postgres, exactly like `tests/voice/test_session_row.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("pipecat.processors.aggregators.llm_context")

from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402

from app.contracts import CaseFile  # noqa: E402
from app.db.models_core import SessionRecord  # noqa: E402
from app.voice import recording  # noqa: E402
from app.voice.recording import persist_voice_session  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402

STARTED = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
ENDED = datetime(2026, 7, 10, 12, 4, 30, tzinfo=UTC)


class _FakeDB:
    """Async-context session double: `get` returns the canned row, `add`/`commit` record."""

    def __init__(self, existing: SessionRecord | None = None) -> None:
        self.existing = existing
        self.added: list[SessionRecord] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, model, pk):  # noqa: ANN001
        assert model is SessionRecord
        return self.existing

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _context_with_turns() -> LLMContext:
    context = LLMContext(messages=[{"role": "system", "content": "SYSTEM"}])
    context.add_message({"role": "assistant", "content": "Thanks for calling Sears."})
    context.add_message({"role": "user", "content": "my dryer won't heat"})
    context.add_message({"role": "assistant", "content": "How old is the unit?"})
    return context


def _install(monkeypatch, fake: _FakeDB) -> None:
    monkeypatch.setattr(recording, "get_sessionmaker", lambda: lambda: fake)


async def test_creates_phone_row_on_a_new_call(monkeypatch):
    fake = _FakeDB(existing=None)
    _install(monkeypatch, fake)
    session = VoiceSession.for_call("CApersist1")
    session.case_file.appliance_type = "dryer"

    await persist_voice_session(session, _context_with_turns(), STARTED, ENDED)

    assert len(fake.added) == 1
    row = fake.added[0]
    assert row.id == session.session_id  # deterministic uuid5(call_sid)
    assert row.channel == "phone"
    assert row.call_sid == "CApersist1"
    assert row.appliance_type == "dryer"
    assert row.started_at == STARTED and row.ended_at == ENDED
    assert fake.commits == 1


async def test_transcript_is_derived_from_context(monkeypatch):
    fake = _FakeDB(existing=None)
    _install(monkeypatch, fake)
    session = VoiceSession.for_call("CApersist2")

    await persist_voice_session(session, _context_with_turns(), STARTED, ENDED)

    row = fake.added[0]
    # system message dropped; roles mapped assistant->agent; order preserved.
    assert row.transcript == [
        {"role": "agent", "text": "Thanks for calling Sears."},
        {"role": "user", "text": "my dryer won't heat"},
        {"role": "agent", "text": "How old is the unit?"},
    ]
    # case_file persisted as JSON-mode dump (a plain dict, not a pydantic model).
    assert isinstance(row.case_file, dict)


async def test_updates_existing_row_in_place(monkeypatch):
    session = VoiceSession.for_call("CApersist3")
    existing = SessionRecord(id=session.session_id, channel="phone", appliance_type="washer")
    fake = _FakeDB(existing=existing)
    _install(monkeypatch, fake)
    session.case_file.appliance_type = "oven"

    await persist_voice_session(session, _context_with_turns(), STARTED, ENDED)

    assert fake.added == []  # no new row — updated the fetched one
    assert existing.appliance_type == "oven"  # overwritten from the live case file
    assert existing.call_sid == "CApersist3"
    assert existing.ended_at == ENDED
    assert fake.commits == 1


async def test_non_casefile_session_falls_back_to_empty_case_file(monkeypatch):
    """Defensive: a session whose `case_file` isn't a CaseFile (corrupt/legacy) upserts a
    default CaseFile rather than raising — recording must never break on odd state."""
    fake = _FakeDB(existing=None)
    _install(monkeypatch, fake)
    session = VoiceSession.for_call("CApersist4")
    session.case_file = "not-a-case-file"  # type: ignore[assignment]

    await persist_voice_session(session, LLMContext(messages=[]), STARTED, ENDED)

    row = fake.added[0]
    assert row.appliance_type is None
    assert row.case_file == CaseFile().model_dump(mode="json")
    assert row.transcript == []
