"""Regression tests for `app/voice/routes.py`'s handshake loop — the raw-JSON
`websocket.receive_text()` read (bounded to `_MAX_HANDSHAKE_FRAMES`) that runs before
Pipecat's own transport/serializer ever sees the socket. A malformed/non-text frame or
an abrupt disconnect during this handshake must not raise out of the route handler —
same "one bad Twilio frame must not kill the call" concern as
`tests/voice/test_serializer.py`, at the pre-Pipecat handshake layer instead.
"""

from __future__ import annotations

import json

import pytest
from fastapi import WebSocketDisconnect

pipecat_frames = pytest.importorskip("pipecat.frames.frames")

import app.voice.routes as routes_module  # noqa: E402


class FakeWebSocket:
    """Minimal stand-in for FastAPI's `WebSocket`, scripted with a fixed inbound
    message sequence. Items that are exception instances are raised from
    `receive_text()` instead of returned, simulating a disconnect or a binary frame."""

    def __init__(self, messages: list) -> None:
        self._messages = list(messages)
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._messages:
            raise WebSocketDisconnect()
        item = self._messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def _start_message(stream_sid: str = "MZ1", call_sid: str = "CA1") -> str:
    return json.dumps({"event": "start", "start": {"streamSid": stream_sid, "callSid": call_sid}})


async def test_malformed_frame_then_valid_start_still_connects(monkeypatch):
    calls = []

    async def fake_run_bot(websocket, stream_sid, call_sid):
        calls.append((stream_sid, call_sid))

    monkeypatch.setattr(routes_module, "run_bot", fake_run_bot)

    ws = FakeWebSocket(["not json", _start_message()])
    await routes_module.twilio_media_stream(ws)

    assert ws.accepted is True
    assert calls == [("MZ1", "CA1")]


async def test_non_text_frame_is_skipped_not_raised(monkeypatch):
    calls = []

    async def fake_run_bot(websocket, stream_sid, call_sid):
        calls.append((stream_sid, call_sid))

    monkeypatch.setattr(routes_module, "run_bot", fake_run_bot)

    ws = FakeWebSocket([RuntimeError("binary frame has no text"), _start_message()])
    await routes_module.twilio_media_stream(ws)

    assert calls == [("MZ1", "CA1")]


async def test_all_malformed_closes_cleanly_without_raising(monkeypatch):
    calls = []
    monkeypatch.setattr(routes_module, "run_bot", lambda *a, **kw: calls.append(a))

    ws = FakeWebSocket(["not json"] * 5)
    await routes_module.twilio_media_stream(ws)

    assert ws.closed is True
    assert calls == []


async def test_disconnect_during_handshake_returns_cleanly(monkeypatch):
    calls = []
    monkeypatch.setattr(routes_module, "run_bot", lambda *a, **kw: calls.append(a))

    ws = FakeWebSocket([WebSocketDisconnect()])
    await routes_module.twilio_media_stream(ws)  # must not raise

    assert calls == []
    assert ws.closed is False  # already disconnected — nothing to close
