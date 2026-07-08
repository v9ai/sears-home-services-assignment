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
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models_core import SessionRecord
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


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(
        recordings_routes, "get_sessionmaker", lambda: _SharedSessionFactory(db_session)
    )
    app = FastAPI()
    app.include_router(recordings_routes.router)
    with TestClient(app) as test_client:
        yield test_client


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

    resp = client.get("/api/recordings", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert [row["id"] for row in body] == [str(newest.id), str(middle.id)]
    assert body[0]["channel"] == "web"
    assert body[0]["turn_count"] == 2

    resp2 = client.get("/api/recordings", params={"limit": 2, "offset": 2})
    assert [row["id"] for row in resp2.json()] == [str(oldest.id)]


@pytest.mark.asyncio
async def test_detail_returns_transcript_with_has_audio_and_case_file(client, db_session):
    record = await _seed(db_session)

    resp = client.get(f"/api/recordings/{record.id}")
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
    resp = client.get(f"/api/recordings/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_backward_compat_transcript_without_ts_or_audio_seq(client, db_session):
    record = await _seed(
        db_session,
        transcript=[{"role": "agent", "text": "Hello"}, {"role": "user", "text": "Hi"}],
    )

    resp = client.get(f"/api/recordings/{record.id}")
    assert resp.status_code == 200
    turns = resp.json()["transcript"]
    assert turns[0] == {
        "role": "agent",
        "text": "Hello",
        "ts": None,
        "has_audio": False,
        "audio_seq": None,
    }

    listing = client.get("/api/recordings").json()
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
