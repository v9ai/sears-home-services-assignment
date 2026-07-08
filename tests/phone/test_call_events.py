"""Structured Twilio call-path event tests (2026-07-09-observability-tracing).

Drives ``handle_twilio_media_stream`` with the same scripted harness as
``test_routes.py``/``test_call_survival.py`` and asserts on the ``event=twilio.*``
log lines rather than internal state — this is what ``wrangler tail`` shows during a
real call.
"""

from __future__ import annotations

import asyncio
import logging

from app.phone.routes import handle_twilio_media_stream
from tests.phone.test_call_survival import SlowEchoAgent, _start, _turn_frames
from tests.phone.test_routes import FakeTranscriber, FakeTwilioWebSocket, RecordingSessionRecorder


class YieldingFakeWebSocket(FakeTwilioWebSocket):
    """Yields to the event loop between inbound frames so a concurrently created
    turn-processing task (F2 decoupling) actually gets scheduled interleaved with
    frame reads — matching real Twilio pacing, where frames arrive with real async
    gaps rather than back-to-back with no scheduler yield. Several ``sleep(0)`` rounds
    per frame (rather than one) make this robust regardless of how many other ready
    callbacks are pending in the loop when run alongside the rest of the suite."""

    async def receive_json(self) -> dict:
        for _ in range(10):
            await asyncio.sleep(0)
        return await super().receive_json()


async def test_call_event_chain_is_complete_and_correlated(caplog):
    transcriber = FakeTranscriber("my washer is broken")
    recorder = RecordingSessionRecorder()
    inbound = [_start(), *_turn_frames(), {"event": "stop"}]
    ws = FakeTwilioWebSocket(inbound)

    with caplog.at_level(logging.INFO, logger="app.phone"):
        await handle_twilio_media_stream(
            ws, transcriber=transcriber, session_recorder=recorder
        )

    text = caplog.text
    assert "event=twilio.stream.start" in text
    assert "call=CAtest" in text
    assert "event=twilio.turn.closed" in text
    assert "event=twilio.stt" in text
    assert "chars=19" in text  # len("my washer is broken")
    assert "event=twilio.turn.processed" in text
    assert "ok=true" in text
    assert "event=twilio.call.summary" in text
    assert "turns=1" in text


async def test_call_summary_counts_frames_and_turns(caplog):
    transcriber = FakeTranscriber("hello")
    agent = SlowEchoAgent(delay=0.01)
    recorder = RecordingSessionRecorder()
    inbound = [_start(), *_turn_frames(), *_turn_frames(), {"event": "stop"}]
    ws = FakeTwilioWebSocket(inbound)

    with caplog.at_level(logging.INFO, logger="app.phone"):
        await handle_twilio_media_stream(
            ws,
            agent_factory=lambda: agent,
            transcriber=transcriber,
            session_recorder=recorder,
        )

    summary_lines = [
        line for line in caplog.text.splitlines() if "event=twilio.call.summary" in line
    ]
    assert len(summary_lines) == 1
    assert "turns=2" in summary_lines[0]
    assert "frames_in=80" in summary_lines[0]  # 2 * len(_turn_frames())


async def test_bargein_event_emitted_mid_playback(caplog):
    """Barge-in fires while the bridge is mid-playback and the frame clears VAD."""
    transcriber = FakeTranscriber("hello")
    agent = SlowEchoAgent(delay=0.2)
    recorder = RecordingSessionRecorder()
    # first turn starts the agent speaking (SlowEchoAgent emits audio then sleeps);
    # immediately follow with more speech frames while it's still "playing".
    inbound = [_start(), *_turn_frames(), *_turn_frames(), {"event": "stop"}]
    ws = YieldingFakeWebSocket(inbound)

    with caplog.at_level(logging.INFO, logger="app.phone"):
        await handle_twilio_media_stream(
            ws,
            agent_factory=lambda: agent,
            transcriber=transcriber,
            session_recorder=recorder,
        )

    assert "event=twilio.bargein" in caplog.text
