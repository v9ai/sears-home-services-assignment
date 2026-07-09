"""The `/ws/twilio` Media Streams route (`app/voice/routes.py`).

Twilio opens the socket and sends `connected` then `start`; the route must read past
`connected`, pull `streamSid`/`callSid` from `start`, and hand the socket to `run_bot`.
`run_bot` (which would spin up the live Pipecat pipeline) is stubbed so the route is
tested in isolation.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pipecat.frames.frames")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.voice import routes as voice_routes  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(voice_routes.router)
    return app


def test_ws_reads_start_and_calls_run_bot(monkeypatch):
    captured: dict = {}

    async def fake_run_bot(websocket, stream_sid, call_sid):
        captured.update(stream_sid=stream_sid, call_sid=call_sid)

    monkeypatch.setattr(voice_routes, "run_bot", fake_run_bot)

    with TestClient(_app()).websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call"}))
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ123",
                        "callSid": "CA456",
                        "customParameters": {"From": "+15550001111"},
                    },
                }
            )
        )

    assert captured == {"stream_sid": "MZ123", "call_sid": "CA456"}


def test_ws_falls_back_to_custom_parameter_call_sid(monkeypatch):
    captured: dict = {}

    async def fake_run_bot(websocket, stream_sid, call_sid):
        captured.update(stream_sid=stream_sid, call_sid=call_sid)

    monkeypatch.setattr(voice_routes, "run_bot", fake_run_bot)

    with TestClient(_app()).websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"streamSid": "MZ9", "customParameters": {"CallSid": "CA_param"}},
                }
            )
        )

    assert captured == {"stream_sid": "MZ9", "call_sid": "CA_param"}
