"""`_speak()` recording-hook tests (validation.md automated gate).

Covers: the mp3 file gets written on a successful synthesis and `audio_seq` lands on
the transcript entry; a recording *write* failure is swallowed and the live call
still gets its transcript + audio frames (spec Decision 5); no file is written when
synthesis itself fails or for a filler line (``record_transcript=False``).
"""

from __future__ import annotations

import itertools
import uuid

import pytest

from app.agent.session_store import SessionState
from app.contracts import CaseFile
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
