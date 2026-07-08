"""WS recording-hook tests (validation.md automated gates).

Covers: the mp3 file gets written on a successful synthesis and `audio_seq` lands on
the transcript entry; a recording *write* failure is swallowed and the live call
still gets its transcript + audio frames (spec Decision 5); no file is written when
synthesis itself fails or for a filler line (``record_transcript=False``); a scripted
full turn produces per-line `ts` + on-disk audio matching each `audio_seq`; and a
pre-feature transcript (entries without `ts`/`audio_seq`) replays text-only.
"""

from __future__ import annotations

import itertools
import logging
import uuid

import pytest

from app.agent.core import SentenceReady, TurnComplete
from app.agent.session_store import SessionState
from app.contracts import CaseFile, TranscriptFrame
from app.ws import routes as ws_routes


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _state() -> SessionState:
    return SessionState(
        session_id=uuid.uuid4(),
        case_file=CaseFile(),
        memory=object(),  # _speak never touches .memory
        transcript=[],
    )


async def _fake_synthesize_ok(text, *, voice="alloy", response_format="mp3"):
    yield b"chunk-one-"
    yield b"chunk-two"


async def _fake_synthesize_fails(text, *, voice="alloy", response_format="mp3"):
    raise RuntimeError("tts down")
    yield b""  # pragma: no cover - never reached, makes this an async generator


@pytest.fixture
def recordings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_routes, "RECORDINGS_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_speak_writes_mp3_and_sets_audio_seq(recordings_dir, monkeypatch):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_ok)
    ws = FakeWebSocket()
    state = _state()

    await ws_routes._speak(ws, "hello there", state, itertools.count(1), itertools.count(1))

    assert state.transcript[-1]["role"] == "agent"
    assert "ts" in state.transcript[-1]
    assert state.transcript[-1]["audio_seq"] == 1
    written = recordings_dir / str(state.session_id) / "00001.mp3"
    assert written.exists()
    assert written.read_bytes() == b"chunk-one-chunk-two"
    assert any(m["type"] == "transcript" for m in ws.sent)
    assert any(m["type"] == "audio" for m in ws.sent)


@pytest.mark.asyncio
async def test_speak_write_failure_is_swallowed(recordings_dir, monkeypatch):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_ok)

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)
    ws = FakeWebSocket()
    state = _state()

    await ws_routes._speak(ws, "hello there", state, itertools.count(1), itertools.count(1))

    assert state.transcript[-1]["role"] == "agent"
    assert "audio_seq" not in state.transcript[-1]
    assert any(m["type"] == "audio" for m in ws.sent)


@pytest.mark.asyncio
async def test_speak_no_audio_file_when_synthesis_fails(recordings_dir, monkeypatch):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_fails)
    ws = FakeWebSocket()
    state = _state()

    await ws_routes._speak(ws, "hello there", state, itertools.count(1), itertools.count(1))

    assert state.transcript[-1]["role"] == "agent"
    assert "audio_seq" not in state.transcript[-1]
    assert not any(m["type"] == "audio" for m in ws.sent)
    assert not (recordings_dir / str(state.session_id)).exists()


@pytest.mark.asyncio
async def test_speak_filler_line_not_recorded(recordings_dir, monkeypatch):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_ok)
    ws = FakeWebSocket()
    state = _state()

    await ws_routes._speak(
        ws, "filler", state, itertools.count(1), itertools.count(1), record_transcript=False
    )

    assert state.transcript == []
    assert not (recordings_dir / str(state.session_id)).exists()


# --- scripted WS turn (validation.md: transcript ts + matching on-disk audio) ------


async def _fake_run_turn_two_sentences(case_file, memory, text, *, session_id=None):
    yield SentenceReady(text="First reply sentence.")
    yield SentenceReady(text="Second reply sentence.")
    yield TurnComplete(full_text="First reply sentence. Second reply sentence.")


@pytest.mark.asyncio
async def test_scripted_ws_turn_records_ts_and_matching_audio(recordings_dir, monkeypatch):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_ok)
    monkeypatch.setattr(ws_routes, "run_turn", _fake_run_turn_two_sentences)
    monkeypatch.setattr(ws_routes, "detect_safety_trigger", lambda text: None)

    persisted: list[SessionState] = []

    async def _fake_persist(state):
        persisted.append(state)

    monkeypatch.setattr(ws_routes, "_persist", _fake_persist)

    ws = FakeWebSocket()
    state = _state()

    await ws_routes._handle_user_text(
        ws, state, "my washer leaks", itertools.count(1), itertools.count(1)
    )

    # user turn + two agent lines, every entry timestamped
    assert [e["role"] for e in state.transcript] == ["user", "agent", "agent"]
    assert all("ts" in e for e in state.transcript)

    # each agent line has a sequential audio_seq with a matching file on disk
    agent_entries = [e for e in state.transcript if e["role"] == "agent"]
    assert [e["audio_seq"] for e in agent_entries] == [1, 2]
    session_dir = recordings_dir / str(state.session_id)
    for entry in agent_entries:
        f = session_dir / f"{entry['audio_seq']:05d}.mp3"
        assert f.exists()
        assert f.read_bytes() == b"chunk-one-chunk-two"

    # live call ran to completion: state frame sent + session persisted
    assert any(m["type"] == "state" for m in ws.sent)
    assert persisted and persisted[-1] is state


@pytest.mark.asyncio
async def test_scripted_ws_turn_write_failure_swallowed_and_logged(
    recordings_dir, monkeypatch, caplog
):
    monkeypatch.setattr(ws_routes, "synthesize", _fake_synthesize_ok)
    monkeypatch.setattr(ws_routes, "run_turn", _fake_run_turn_two_sentences)
    monkeypatch.setattr(ws_routes, "detect_safety_trigger", lambda text: None)

    async def _fake_persist(state):
        return None

    monkeypatch.setattr(ws_routes, "_persist", _fake_persist)

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)

    ws = FakeWebSocket()
    state = _state()

    with caplog.at_level(logging.ERROR, logger="app.ws"):
        await ws_routes._handle_user_text(
            ws, state, "my washer leaks", itertools.count(1), itertools.count(1)
        )

    # call unaffected: transcript + audio frames delivered, turn completed
    assert [e["role"] for e in state.transcript] == ["user", "agent", "agent"]
    assert not any("audio_seq" in e for e in state.transcript)
    assert any(m["type"] == "audio" for m in ws.sent)
    assert any(m["type"] == "state" for m in ws.sent)
    # failure was logged, not raised
    assert "recording_write_failed" in caplog.text


# --- backward compat (validation.md: pre-feature transcript replays text-only) -----


def test_pre_feature_transcript_replays_text_only():
    """Mirrors ``ws_call``'s replay loop: entries lacking ts/audio_seq must not error."""
    transcript = [
        {"role": "user", "text": "my dryer won't heat"},
        {"role": "agent", "text": "How old is the unit?"},
        # a post-feature entry with the new optional keys coexists in the same list
        {"role": "user", "text": "about three years", "ts": "2026-07-08T00:00:00+00:00"},
        {
            "role": "agent",
            "text": "Got it, thanks.",
            "ts": "2026-07-08T00:00:01+00:00",
            "audio_seq": 1,
        },
    ]

    frames = [
        TranscriptFrame(role=line["role"], text=line["text"]).model_dump() for line in transcript
    ]

    assert [f["text"] for f in frames] == [
        "my dryer won't heat",
        "How old is the unit?",
        "about three years",
        "Got it, thanks.",
    ]
    # the frame contract carries no ts/audio_seq — replay is purely role+text
    assert all(set(f) == {"type", "role", "text"} for f in frames)
