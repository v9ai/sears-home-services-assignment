"""End-to-end tests for the `/ws/call` WebSocket entrypoint (`app/ws/routes.py:ws_call`).

`ws_call` is the web voice channel's front door — it was 0-covered: session load, the
initial state frame, transcript replay, the new-session greeting, the receive loop that
routes user-text frames (skipping malformed ones), and clean teardown on disconnect. These
tests drive it through a real FastAPI `TestClient.websocket_connect`, with the DB, TTS synth,
persistence, and the agent turn all monkeypatched so the run is hermetic (no Postgres, no
network). The concurrent P0-2 filler is suppressed (`should_fire_filler` -> False) so frame
ordering is deterministic; the filler itself is covered in tests/voice/test_fillers.py.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("pipecat.frames.frames")

from app.agent.core import SentenceReady, TurnComplete  # noqa: E402
from app.agent.session_store import SessionState  # noqa: E402
from app.contracts import CaseFile  # noqa: E402
from app.ws import routes as ws_routes  # noqa: E402

GREETING_TEXT = "Thanks for calling Sears Home Services!"


class _FakeDB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    def add(self, _obj) -> None:  # used by the real load_or_create_session fresh path
        pass

    async def commit(self) -> None:
        pass


async def _one_chunk_synth(_text):
    """Deterministic 1-frame synth stand-in — keeps greeting/reply audio counts fixed."""
    yield b"\x00\x00\x00\x00"


def _make_state(*, is_new: bool, transcript=None) -> SessionState:
    return SessionState(
        session_id=uuid.uuid4(),
        case_file=CaseFile(),
        memory=object(),  # run_turn is faked; nothing touches .memory
        transcript=list(transcript or []),
        is_new=is_new,
    )


def _client(
    monkeypatch, tmp_path, state: SessionState, *, reply: str = "Let's get it fixed."
) -> TestClient:
    async def _fake_load(_db, _session_id):
        return state

    async def _fake_run_turn(case_file, memory, text, *, session_id=None, trace=None):
        yield SentenceReady(text=reply)
        yield TurnComplete(full_text=reply)

    monkeypatch.setattr(ws_routes, "get_sessionmaker", lambda: _FakeDB)
    monkeypatch.setattr(ws_routes, "load_or_create_session", _fake_load)
    monkeypatch.setattr(ws_routes, "_synth", _one_chunk_synth)
    monkeypatch.setattr(ws_routes, "run_turn", _fake_run_turn)
    monkeypatch.setattr(ws_routes, "detect_safety_trigger", lambda _text: None)
    monkeypatch.setattr(ws_routes, "should_fire_filler", lambda *_a: False)
    monkeypatch.setattr(ws_routes, "_persist_async", lambda _state: None)
    monkeypatch.setattr(ws_routes, "GREETING", GREETING_TEXT)
    monkeypatch.setattr(ws_routes, "RECORDINGS_DIR", str(tmp_path))

    app = FastAPI()
    app.include_router(ws_routes.router)
    return TestClient(app)


def _drain_until_state(ws, cap: int = 40) -> list[dict]:
    """Collect frames up to and including the end-of-turn state frame."""
    frames = []
    for _ in range(cap):
        frame = ws.receive_json()
        frames.append(frame)
        if frame["type"] == "state":
            return frames
    raise AssertionError("no state frame within cap")


def test_new_session_gets_state_then_greeting(monkeypatch, tmp_path):
    state = _make_state(is_new=True)
    client = _client(monkeypatch, tmp_path, state)

    with client.websocket_connect("/ws/call?session_id=abc") as ws:
        state_frame = ws.receive_json()
        greeting = ws.receive_json()
        audio = ws.receive_json()

        assert state_frame["type"] == "state"
        assert greeting["type"] == "transcript"
        assert greeting["role"] == "agent"
        assert greeting["text"] == GREETING_TEXT
        assert audio["type"] == "audio"


def test_existing_session_replays_transcript_and_skips_greeting(monkeypatch, tmp_path):
    transcript = [
        {"role": "user", "text": "my dryer won't heat"},
        {"role": "agent", "text": "How old is the unit?"},
    ]
    state = _make_state(is_new=False, transcript=transcript)
    client = _client(monkeypatch, tmp_path, state)

    with client.websocket_connect("/ws/call?session_id=returning") as ws:
        assert ws.receive_json()["type"] == "state"
        replayed = [ws.receive_json() for _ in transcript]
        assert [(f["role"], f["text"]) for f in replayed] == [
            ("user", "my dryer won't heat"),
            ("agent", "How old is the unit?"),
        ]
        # No greeting for a returning session: the next thing is our sent turn's echo.
        ws.send_json({"type": "user_text", "text": "still broken"})
        frames = _drain_until_state(ws)
        assert any(f["type"] == "transcript" and f["role"] == "user" for f in frames)


def test_user_text_frame_routes_to_a_reply(monkeypatch, tmp_path):
    state = _make_state(is_new=False)
    client = _client(monkeypatch, tmp_path, state, reply="Sorry to hear that.")

    with client.websocket_connect("/ws/call?session_id=s1") as ws:
        assert ws.receive_json()["type"] == "state"  # initial state
        ws.send_json({"type": "user_text", "text": "my washer leaks"})

        frames = _drain_until_state(ws)

        transcripts = [(f["role"], f["text"]) for f in frames if f["type"] == "transcript"]
        assert ("user", "my washer leaks") in transcripts
        assert ("agent", "Sorry to hear that.") in transcripts
        assert frames[-1]["type"] == "state"  # turn ends with a fresh state frame


def test_malformed_frame_is_skipped_not_fatal(monkeypatch, tmp_path):
    state = _make_state(is_new=False)
    client = _client(monkeypatch, tmp_path, state, reply="Got it.")

    with client.websocket_connect("/ws/call?session_id=s2") as ws:
        assert ws.receive_json()["type"] == "state"
        # A frame that fails UserTextFrame validation must be logged and skipped...
        ws.send_json({"not": "a valid user_text frame"})
        # ...and the connection stays usable: a real frame right after still routes.
        ws.send_json({"type": "user_text", "text": "hello"})

        frames = _drain_until_state(ws)
        transcripts = [(f["role"], f["text"]) for f in frames if f["type"] == "transcript"]
        assert ("user", "hello") in transcripts
        assert ("agent", "Got it.") in transcripts


def test_safety_trigger_interrupts_with_fixed_response(monkeypatch, tmp_path):
    """A hazard utterance takes the pre-LLM safety branch: the fixed SAFETY_RESPONSE is
    spoken, the case file's safety_flag is set, and run_turn never runs."""
    from app.agent.safety import SAFETY_RESPONSE

    state = _make_state(is_new=False)
    client = _client(monkeypatch, tmp_path, state)

    called = {"run_turn": False}

    async def _must_not_run(*_a, **_k):
        called["run_turn"] = True
        yield  # pragma: no cover

    monkeypatch.setattr(ws_routes, "run_turn", _must_not_run)
    monkeypatch.setattr(ws_routes, "detect_safety_trigger", lambda _text: "electrical")

    with client.websocket_connect("/ws/call?session_id=s4") as ws:
        assert ws.receive_json()["type"] == "state"
        ws.send_json({"type": "user_text", "text": "there is sparking from the oven"})

        frames = _drain_until_state(ws)
        transcripts = [(f["role"], f["text"]) for f in frames if f["type"] == "transcript"]
        assert ("agent", SAFETY_RESPONSE) in transcripts

    assert called["run_turn"] is False
    assert state.case_file.safety_flag is True


def test_agent_turn_failure_speaks_the_fallback(monkeypatch, tmp_path):
    """If the agent turn raises before any sentence streams, the caller still hears the
    turn-failed fallback line rather than dead air — and the socket stays open."""
    state = _make_state(is_new=False)
    client = _client(monkeypatch, tmp_path, state)

    async def _boom_run_turn(*_a, **_k):
        raise RuntimeError("llm exploded")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(ws_routes, "run_turn", _boom_run_turn)

    with client.websocket_connect("/ws/call?session_id=s5") as ws:
        assert ws.receive_json()["type"] == "state"
        ws.send_json({"type": "user_text", "text": "my fridge is warm"})

        frames = _drain_until_state(ws)
        transcripts = [(f["role"], f["text"]) for f in frames if f["type"] == "transcript"]
        assert ("user", "my fridge is warm") in transcripts
        assert ("agent", ws_routes.TURN_FAILED_FALLBACK) in transcripts


def test_disconnect_before_any_turn_exits_cleanly(monkeypatch, tmp_path):
    state = _make_state(is_new=False)
    client = _client(monkeypatch, tmp_path, state)

    # Opening then immediately closing must not raise out of the handler (the
    # WebSocketDisconnect is caught in the receive loop).
    with client.websocket_connect("/ws/call?session_id=s3") as ws:
        assert ws.receive_json()["type"] == "state"
    # Reaching here without an exception is the assertion.


def test_malformed_session_id_query_param_connects_as_fresh_session(monkeypatch, tmp_path):
    """Route-layer pin for the task #26 fix: a garbage ?session_id must degrade to a fresh
    session (is_new -> greeting) instead of 500-ing the connect. Runs the REAL
    load_or_create_session against a fake DB — the malformed-id path skips db.get and
    creates a fresh row, so no Postgres is needed."""
    monkeypatch.setattr(ws_routes, "get_sessionmaker", lambda: _FakeDB)
    monkeypatch.setattr(ws_routes, "_synth", _one_chunk_synth)
    monkeypatch.setattr(ws_routes, "should_fire_filler", lambda *_a: False)
    monkeypatch.setattr(ws_routes, "_persist_async", lambda _state: None)
    monkeypatch.setattr(ws_routes, "GREETING", GREETING_TEXT)
    monkeypatch.setattr(ws_routes, "RECORDINGS_DIR", str(tmp_path))
    # NOTE: load_or_create_session is deliberately NOT patched here.

    app = FastAPI()
    app.include_router(ws_routes.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/call?session_id=not-a-uuid") as ws:
        assert ws.receive_json()["type"] == "state"
        greeting = ws.receive_json()
        assert greeting["type"] == "transcript"
        assert greeting["text"] == GREETING_TEXT  # fresh session -> greeted, no raise
