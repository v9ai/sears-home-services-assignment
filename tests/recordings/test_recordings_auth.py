"""Optional token-gate tests for the recordings router (RECORDINGS_ACCESS_TOKEN).

Backwards-compatibility contract:
  * unset/empty  -> gate disabled, every route open exactly as before (Decision 2);
  * set          -> every route (list/detail/audio/call-audio/twilio-audio) requires the
                    token via `Authorization: Bearer <token>` OR `?token=<token>`; wrong
                    or missing -> 401, compared in constant time.

These use a bare in-process app + FastAPI TestClient so they need no DB: the gate runs as
a router-level dependency *before* any handler, so a 401 short-circuits before a DB query
and a 200/404 confirms the request was let through to the (DB-less) filesystem probe.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.recordings import routes as recordings_routes

TOKEN = "s3cret-demo-token"


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    # Point audio at an empty temp dir so unauthenticated probes can't accidentally hit a
    # real recording; the gate is what these tests exercise, not audio bytes.
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(recordings_routes.router)
    return TestClient(app)


# --------------------------------------------------------------- gate disabled (default)


def test_unset_token_leaves_all_routes_open(monkeypatch, app_client):
    """Unset RECORDINGS_ACCESS_TOKEN -> original open behavior, no auth needed."""
    monkeypatch.delenv("RECORDINGS_ACCESS_TOKEN", raising=False)
    rid = uuid.uuid4()

    # list reaches the DB layer (no DB configured here -> 500, but crucially NOT 401):
    # the point is the gate did not reject it. audio/call-audio are pure fs probes -> 404.
    assert app_client.get(f"/api/recordings/{rid}/audio/1").status_code == 404
    assert app_client.get(f"/api/recordings/{rid}/call-audio").status_code == 404


def test_empty_token_is_treated_as_unset(monkeypatch, app_client):
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", "   ")
    rid = uuid.uuid4()
    assert app_client.get(f"/api/recordings/{rid}/audio/1").status_code == 404


# ------------------------------------------------------------------ gate enabled -> 401


def test_set_token_missing_credential_is_401(monkeypatch, app_client):
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    rid = uuid.uuid4()
    for path in (
        "/api/recordings",
        f"/api/recordings/{rid}",
        f"/api/recordings/{rid}/audio/1",
        f"/api/recordings/{rid}/call-audio",
        f"/api/recordings/{rid}/twilio-audio/RE123",
    ):
        resp = app_client.get(path)
        assert resp.status_code == 401, path
        assert resp.headers.get("www-authenticate") == "Bearer"


def test_set_token_wrong_bearer_is_401(monkeypatch, app_client):
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    resp = app_client.get(
        "/api/recordings", headers={"Authorization": "Bearer not-the-token"}
    )
    assert resp.status_code == 401


def test_set_token_wrong_query_param_is_401(monkeypatch, app_client):
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    resp = app_client.get("/api/recordings", params={"token": "nope"})
    assert resp.status_code == 401


# --------------------------------------------------------- gate enabled -> good token OK


def test_set_token_good_bearer_passes_gate(monkeypatch, app_client):
    """Correct Bearer token -> request is admitted (fs probe answers 404, not 401)."""
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    rid = uuid.uuid4()
    resp = app_client.get(
        f"/api/recordings/{rid}/audio/1", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 404  # admitted past the gate; audio simply absent


def test_set_token_good_query_param_passes_gate(monkeypatch, app_client):
    """Correct ?token= -> admitted. This is the header-less path a browser <audio> uses."""
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    rid = uuid.uuid4()
    resp = app_client.get(f"/api/recordings/{rid}/call-audio", params={"token": TOKEN})
    assert resp.status_code == 404  # admitted past the gate; call.wav simply absent


def test_good_query_param_serves_audio_end_to_end(monkeypatch, tmp_path):
    """Full end-to-end: token gate on, a real call.wav on disk, browser-style ?token=
    query -> the audio bytes actually stream (200), proving the header-less flow works."""
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    monkeypatch.setattr(recordings_routes, "RECORDINGS_DIR", str(tmp_path))
    rid = uuid.uuid4()
    session_dir = tmp_path / str(rid)
    session_dir.mkdir()
    (session_dir / "call.wav").write_bytes(b"RIFF----WAVEfake")

    app = FastAPI()
    app.include_router(recordings_routes.router)
    client = TestClient(app)

    assert client.get(f"/api/recordings/{rid}/call-audio").status_code == 401
    ok = client.get(f"/api/recordings/{rid}/call-audio", params={"token": TOKEN})
    assert ok.status_code == 200
    assert ok.content == b"RIFF----WAVEfake"


# ---------------------------------------------------------------- helper-level behavior


def test_authorize_media_url_noop_when_open(monkeypatch):
    monkeypatch.delenv("RECORDINGS_ACCESS_TOKEN", raising=False)
    assert recordings_routes._authorize_media_url("/api/recordings/x/call-audio") == (
        "/api/recordings/x/call-audio"
    )


def test_authorize_media_url_appends_token_when_gated(monkeypatch):
    monkeypatch.setenv("RECORDINGS_ACCESS_TOKEN", TOKEN)
    assert recordings_routes._authorize_media_url("/api/recordings/x/call-audio") == (
        f"/api/recordings/x/call-audio?token={TOKEN}"
    )
    # appends with & when the URL already has a query string
    assert recordings_routes._authorize_media_url("/x?a=1") == f"/x?a=1&token={TOKEN}"


def test_gate_uses_constant_time_comparison(monkeypatch):
    """Guard against a future refactor swapping hmac.compare_digest for ==."""
    import inspect

    src = inspect.getsource(recordings_routes.require_recordings_access)
    assert "compare_digest" in src
