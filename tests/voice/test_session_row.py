"""`ensure_voice_session_row` (2026-07-09-booking-session-attribution): the phone
channel's `sessions` row is created at call START so a mid-call `book_appointment`
has its `appointments.session_id` FK target — `persist_voice_session` (call end)
keeps ownership of the full update. Hermetic: a fake session factory stands in for
the DB, same style as the other voice fakes.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("pipecat.frames.frames")

from app.db.models_core import SessionRecord  # noqa: E402
from app.voice import recording  # noqa: E402
from app.voice.recording import ensure_voice_session_row  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402


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


async def test_creates_minimal_phone_row_at_call_start(monkeypatch):
    fake = _FakeDB(existing=None)
    monkeypatch.setattr(recording, "get_sessionmaker", lambda: lambda: fake)
    session = VoiceSession.for_call("CAattr1")

    await ensure_voice_session_row(session)

    assert len(fake.added) == 1
    row = fake.added[0]
    assert row.id == session.session_id  # deterministic uuid5(CallSid)
    assert row.channel == "phone"
    assert row.call_sid == "CAattr1"
    assert fake.commits == 1


async def test_idempotent_when_row_already_exists(monkeypatch):
    session = VoiceSession.for_call("CAattr2")
    fake = _FakeDB(existing=SessionRecord(id=session.session_id, channel="phone"))
    monkeypatch.setattr(recording, "get_sessionmaker", lambda: lambda: fake)

    await ensure_voice_session_row(session)

    assert fake.added == []
    assert fake.commits == 0


async def test_db_failure_never_raises_only_logs(monkeypatch, caplog):
    def _broken_sessionmaker():
        raise RuntimeError("db down")

    monkeypatch.setattr(recording, "get_sessionmaker", _broken_sessionmaker)
    session = VoiceSession.for_call("CAattr3")

    with caplog.at_level(logging.INFO, logger="app.voice.recording"):
        await ensure_voice_session_row(session)  # must not raise

    assert any("event=voice.session_row.ensure_failed" in r.message for r in caplog.records)
