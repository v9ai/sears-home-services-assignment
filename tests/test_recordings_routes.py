"""HTTP-level recordings route tests (validation.md automated gate).

Standalone FastAPI app around just the recordings router, with the DB dependency
swapped for the shared ``db_session`` fixture (real Postgres, rolled back after each
test — skips, never fails, when no reachable Postgres is configured, same as every
other DB-backed test file in this suite). No auth headers anywhere, matching the
spec's explicit no-auth directive.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from app.db.models_core import SessionRecord
from app.phone.twilio_client import TwilioConfigError
from app.recordings import routes as recordings_routes


class _SharedSessionFactory:
    """Hands every ``async with session_factory() as db`` the *same* transactional
    session the test itself is using, so route-side queries see the test's
    unflushed/uncommitted inserts without a real commit ever happening."""

    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # Hermetic paging: dev databases accumulate real sessions (compose smoke runs,
    # local calls) and the list/offset assertions below page over the WHOLE table —
    # clear it inside the test's (rolled-back) transaction first. Appointments go
    # first: `appointments.session_id` (booking-session-attribution) references
    # sessions, so the blanket session delete FK-violates on a dev DB with real
    # attributed bookings.
    from sqlalchemy import delete

    from app.db.models_scheduling import Appointment

    await db_session.execute(delete(Appointment))
    await db_session.execute(delete(SessionRecord))
    # Drive the ASGI app in-loop (httpx ASGITransport) so route-side queries share the
    # test's asyncpg connection; a threaded TestClient runs its own event loop and an
    # asyncpg connection can't cross loops.
    monkeypatch.setattr(
        recordings_routes, "get_sessionmaker", lambda: _SharedSessionFactory(db_session)
    )
    app = FastAPI()
    app.include_router(recordings_routes.router)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _seed(db_session, **overrides) -> SessionRecord:
    defaults = dict(
        id=uuid.uuid4(),
        channel="web",
        appliance_type="washer",
        case_file={"appliance_type": "washer"},
        transcript=[
            {
                "role": "agent",
                "text": "Hi there",
                "ts": "2026-07-08T10:00:00+00:00",
                "audio_seq": 1,
            },
            {"role": "user", "text": "My washer is leaking", "ts": "2026-07-08T10:00:05+00:00"},
        ],
        started_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    record = SessionRecord(**defaults)
    db_session.add(record)
    await db_session.flush()
    return record


@pytest.mark.asyncio
async def test_list_is_newest_first_and_respects_limit_offset(client, db_session):
    now = datetime.now(UTC)
    oldest = await _seed(db_session, started_at=now - timedelta(minutes=10))
    middle = await _seed(db_session, started_at=now - timedelta(minutes=5))
    newest = await _seed(db_session, started_at=now)

    resp = await client.get("/api/recordings", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert [row["id"] for row in body] == [str(newest.id), str(middle.id)]
    assert body[0]["channel"] == "web"
    assert body[0]["turn_count"] == 2

    resp2 = await client.get("/api/recordings", params={"limit": 2, "offset": 2})
    assert [row["id"] for row in resp2.json()] == [str(oldest.id)]


@pytest.mark.asyncio
async def test_detail_returns_transcript_with_has_audio_and_case_file(client, db_session):
    record = await _seed(db_session)

    resp = await client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_file"]["appliance_type"] == "washer"
    turns = body["transcript"]
    assert turns[0] == {
        "role": "agent",
        "text": "Hi there",
        "ts": "2026-07-08T10:00:00+00:00",
        "has_audio": True,
        "audio_seq": 1,
    }
    assert turns[1]["has_audio"] is False
    assert turns[1]["audio_seq"] is None


@pytest.mark.asyncio
async def test_detail_404_for_unknown_id(client):
    resp = await client.get(f"/api/recordings/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_backward_compat_transcript_without_ts_or_audio_seq(client, db_session):
    record = await _seed(
        db_session,
        transcript=[{"role": "agent", "text": "Hello"}, {"role": "user", "text": "Hi"}],
    )

    resp = await client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    turns = resp.json()["transcript"]
    assert turns[0] == {
        "role": "agent",
        "text": "Hello",
        "ts": None,
        "has_audio": False,
        "audio_seq": None,
    }

    listing = (await client.get("/api/recordings")).json()
    assert any(row["id"] == str(record.id) for row in listing)


def test_audio_endpoint_serves_bytes_and_404s_on_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))
    session_id = uuid.uuid4()
    session_dir = tmp_path / str(session_id)
    session_dir.mkdir()
    (session_dir / "00001.mp3").write_bytes(b"fake-mp3-bytes")

    app = FastAPI()
    app.include_router(recordings_routes.router)
    with TestClient(app) as test_client:
        ok = test_client.get(f"/api/recordings/{session_id}/audio/1")
        assert ok.status_code == 200
        assert ok.content == b"fake-mp3-bytes"
        assert ok.headers["content-type"] == "audio/mpeg"

        missing_seq = test_client.get(f"/api/recordings/{session_id}/audio/2")
        assert missing_seq.status_code == 404

        missing_session = test_client.get(f"/api/recordings/{uuid.uuid4()}/audio/1")
        assert missing_session.status_code == 404


def test_audio_endpoint_serves_wav(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))
    session_id = uuid.uuid4()
    session_dir = tmp_path / str(session_id)
    session_dir.mkdir()
    (session_dir / "00003.wav").write_bytes(b"fake-wav-bytes")

    app = FastAPI()
    app.include_router(recordings_routes.router)
    with TestClient(app) as test_client:
        resp = test_client.get(f"/api/recordings/{session_id}/audio/3")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"


def test_recordings_dir_env_default():
    assert recordings_routes.RECORDINGS_DIR == os.environ.get("RECORDINGS_DIR", "data/recordings")


@pytest.mark.asyncio
async def test_all_endpoints_reachable_with_no_auth_headers(client, db_session):
    """The spec's explicit no-auth directive: list/detail/audio all answer with zero
    auth headers on the request (Decision 2)."""
    record = await _seed(db_session)

    assert (await client.get("/api/recordings")).status_code == 200
    assert (await client.get(f"/api/recordings/{record.id}")).status_code == 200
    # audio 404 (no file on disk, fallback off) is still an un-authenticated answer
    assert (await client.get(f"/api/recordings/{record.id}/audio/1")).status_code == 404


def test_audio_fallback_off_by_default_returns_404(monkeypatch, tmp_path):
    """`REPLAY_TTS_FALLBACK` unset → missing audio is a clean 404, no re-synthesis."""
    monkeypatch.delenv("REPLAY_TTS_FALLBACK", raising=False)
    assert recordings_routes._tts_fallback_enabled() is False
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))

    app = FastAPI()
    app.include_router(recordings_routes.router)
    with TestClient(app) as test_client:
        resp = test_client.get(f"/api/recordings/{uuid.uuid4()}/audio/1")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audio_fallback_on_resynthesizes_from_transcript_text(
    client, db_session, monkeypatch, tmp_path
):
    """`REPLAY_TTS_FALLBACK` on + no stored file → re-synthesize the turn's persisted
    text and stream it as audio/mpeg (Decision 1, flagged fallback)."""
    monkeypatch.setenv("REPLAY_TTS_FALLBACK", "true")
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))

    captured: dict = {}

    async def _fake_synthesize(text, *, voice="alloy", response_format="mp3"):
        captured["text"] = text
        yield b"resynth:"
        yield text.encode()

    monkeypatch.setattr(recordings_routes.tts, "synthesize", _fake_synthesize)

    record = await _seed(db_session)  # turn seq 1 = agent "Hi there"
    resp = await client.get(f"/api/recordings/{record.id}/audio/1")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"resynth:Hi there"
    assert captured["text"] == "Hi there"


@pytest.mark.asyncio
async def test_audio_fallback_on_404s_when_no_matching_turn(
    client, db_session, monkeypatch, tmp_path
):
    """Fallback on but the seq has no transcript turn (or no text) → still 404."""
    monkeypatch.setenv("REPLAY_TTS_FALLBACK", "1")
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))
    record = await _seed(db_session)

    resp = await client.get(f"/api/recordings/{record.id}/audio/999")
    assert resp.status_code == 404


# --------------------------------------------------------------------- Twilio recordings


@dataclass
class _FakeTwilioRecording:
    sid: str
    status: str = "completed"
    duration: str = "42"
    channels: int = 2
    date_created: datetime | None = None


class _FakeRecordingsResource:
    def __init__(self, recordings: list[_FakeTwilioRecording]) -> None:
        self._recordings = recordings

    def list(self, call_sid=None):
        return list(self._recordings)


class _FakeTwilioClient:
    def __init__(self, recordings: list[_FakeTwilioRecording]) -> None:
        self.recordings = _FakeRecordingsResource(recordings)


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        pass

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeStreamCtx:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self):
        return _FakeStreamResponse(self._chunks)

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeHttpxAsyncClient:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    def stream(self, method, url):
        return _FakeStreamCtx(self._chunks)


@pytest.mark.asyncio
async def test_list_reports_has_call_sid(client, db_session):
    with_call = await _seed(db_session, call_sid="CA_with")
    without_call = await _seed(db_session)

    body = (await client.get("/api/recordings")).json()
    by_id = {row["id"]: row for row in body}
    assert by_id[str(with_call.id)]["has_call_sid"] is True
    assert by_id[str(without_call.id)]["has_call_sid"] is False


@pytest.mark.asyncio
async def test_detail_without_call_sid_skips_twilio_lookup(client, db_session, monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("should not look up Twilio when call_sid is unset")

    monkeypatch.setattr(recordings_routes, "get_twilio_client", _boom)
    record = await _seed(db_session)

    resp = await client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    assert resp.json()["twilio_recordings"] == []


@pytest.mark.asyncio
async def test_detail_with_call_sid_returns_twilio_recordings(client, db_session, monkeypatch):
    fake_recording = _FakeTwilioRecording(sid="RE123")
    monkeypatch.setattr(
        recordings_routes, "get_twilio_client", lambda: _FakeTwilioClient([fake_recording])
    )
    record = await _seed(db_session, call_sid="CA123")

    resp = await client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    recordings = resp.json()["twilio_recordings"]
    assert len(recordings) == 1
    assert recordings[0]["sid"] == "RE123"
    assert recordings[0]["duration_seconds"] == 42
    assert recordings[0]["channels"] == 2
    assert recordings[0]["media_url"] == f"/api/recordings/{record.id}/twilio-audio/RE123"


@pytest.mark.asyncio
async def test_detail_twilio_lookup_failure_degrades_gracefully(client, db_session, monkeypatch):
    def _raise():
        raise TwilioConfigError("not configured")

    monkeypatch.setattr(recordings_routes, "get_twilio_client", _raise)
    record = await _seed(db_session, call_sid="CA123")

    resp = await client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    assert resp.json()["twilio_recordings"] == []


@pytest.mark.asyncio
async def test_twilio_audio_proxy_404_without_call_sid(client, db_session):
    record = await _seed(db_session)
    resp = await client.get(f"/api/recordings/{record.id}/twilio-audio/RE123")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_twilio_audio_proxy_404_for_unowned_sid(client, db_session, monkeypatch):
    monkeypatch.setattr(
        recordings_routes,
        "get_twilio_client",
        lambda: _FakeTwilioClient([_FakeTwilioRecording(sid="RE_owned")]),
    )
    record = await _seed(db_session, call_sid="CA123")

    resp = await client.get(f"/api/recordings/{record.id}/twilio-audio/RE_not_owned")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_twilio_audio_proxy_streams_bytes(client, db_session, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token_test")
    monkeypatch.setattr(
        recordings_routes,
        "get_twilio_client",
        lambda: _FakeTwilioClient([_FakeTwilioRecording(sid="RE123")]),
    )
    monkeypatch.setattr(
        recordings_routes.httpx, "AsyncClient", _FakeHttpxAsyncClient([b"ab", b"cd"])
    )
    record = await _seed(db_session, call_sid="CA123")

    resp = await client.get(f"/api/recordings/{record.id}/twilio-audio/RE123")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"abcd"
