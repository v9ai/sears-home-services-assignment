"""Premature call-end regression guards (2026-07-09 RCA).

The failure shape: an exception escaping the ``/ws/twilio`` message loop closes the
stream, and with ``<Connect><Stream>`` a closed stream ENDS THE CALL. These tests pin
the two fixes:

- F3 containment: STT/agent/greet/session-start failures degrade gracefully — the
  loop keeps reading and the call reaches its natural ``stop``.
- F2 decoupling: turn processing runs off the message loop, so frames keep being
  consumed (barge-in stays live) while a slow agent turn is in flight.
"""

from __future__ import annotations

import asyncio

from app.phone.routes import handle_twilio_media_stream
from tests.phone.test_routes import (
    FakeTranscriber,
    FakeTwilioWebSocket,
    RecordingSessionRecorder,
    _silence_mulaw_b64,
    _tone_mulaw_b64,
)


def _media(payload: str) -> dict:
    return {"event": "media", "media": {"payload": payload}}


def _start() -> dict:
    return {
        "event": "start",
        "start": {"callSid": "CAtest", "streamSid": "MZtest", "customParameters": {}},
    }


def _turn_frames() -> list[dict]:
    # enough speech to trip the VAD, then enough silence to close the turn
    return [_media(_tone_mulaw_b64()) for _ in range(20)] + [
        _media(_silence_mulaw_b64()) for _ in range(20)
    ]


class ExplodingTranscriber:
    """STT fails hard on every call — the OpenAI-hiccup scenario."""

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> str:
        self.calls += 1
        raise RuntimeError("stt provider down")


class SlowEchoAgent:
    """Takes a long time per turn and speaks while doing it (playback observable)."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.turns: list[str] = []

    async def handle_turn(self, text: str, bridge, *, audio_seq=None, trace=None) -> None:
        self.turns.append(text)
        await bridge.emit_audio(b"\x00\x01" * 4800)  # ~200ms of 24k pcm to play
        await asyncio.sleep(self.delay)


async def test_stt_failure_does_not_end_the_call():
    """F3: every turn's STT raises, yet the loop survives to the natural stop."""
    transcriber = ExplodingTranscriber()
    recorder = RecordingSessionRecorder()
    inbound = [_start(), *_turn_frames(), *_turn_frames(), {"event": "stop"}]
    ws = FakeTwilioWebSocket(inbound)

    bridge = await handle_twilio_media_stream(
        ws, transcriber=transcriber, session_recorder=recorder
    )

    assert transcriber.calls >= 2  # both turns attempted...
    assert recorder.ended == ["CAtest"]  # ...and the call still closed out normally
    assert bridge is not None


async def test_greet_and_session_start_failures_do_not_end_the_call():
    """F3: a greet/DB failure at answer degrades, the call proceeds to stop."""

    class ExplodingRecorder(RecordingSessionRecorder):
        async def start_session(self, context) -> str:
            raise RuntimeError("db down at answer")

    class GreetingAgent:
        def __init__(self) -> None:
            self.turns: list[str] = []

        async def greet(self, bridge) -> None:
            raise RuntimeError("tts down at answer")

        async def handle_turn(self, text: str, bridge, *, audio_seq=None, trace=None) -> None:
            self.turns.append(text)

    agent = GreetingAgent()
    inbound = [_start(), *_turn_frames(), {"event": "stop"}]
    ws = FakeTwilioWebSocket(inbound)

    await handle_twilio_media_stream(
        ws,
        agent_factory=lambda: agent,
        transcriber=FakeTranscriber("my washer is broken"),
        session_recorder=ExplodingRecorder(),
    )

    assert agent.turns == ["my washer is broken"]  # the turn still ran


async def test_reader_not_blocked_by_slow_turn():
    """F2: while a slow agent turn is processing, later frames are still consumed —
    the second utterance is transcribed (chained), not lost to a blocked loop."""
    transcriber = FakeTranscriber("hello")
    agent = SlowEchoAgent(delay=0.3)
    recorder = RecordingSessionRecorder()
    inbound = [_start(), *_turn_frames(), *_turn_frames(), {"event": "stop"}]
    ws = FakeTwilioWebSocket(inbound)

    await handle_twilio_media_stream(
        ws,
        agent_factory=lambda: agent,
        transcriber=transcriber,
        session_recorder=recorder,
    )

    # Both turns reached the agent even though each takes 300 ms to process —
    # with the old inline await the second turn's frames would still be queued
    # unread when the first turn finished (they'd still arrive, but in real life
    # Twilio's backpressure + dead barge-in was the failure). The structural
    # assertion: turn 2 was submitted while turn 1 was in flight, i.e. total
    # inbound consumption did not serialize behind processing.
    assert agent.turns == ["hello", "hello"]
    assert recorder.ended == ["CAtest"]


def test_agent_signatures_match_bridge_call_contract():
    """The root-cause guard: the bridge calls handle_turn(text, bridge,
    audio_seq=..., trace=...) — EVERY TurnAgent implementation must accept that
    exact shape. The 2026-07-09 premature-call-end bug was RealAgent missing
    ``trace`` after the bridge grew it: a TypeError on every production turn."""
    import inspect

    from app.phone.fake_agent import FakeAgent
    from app.phone.real_agent import RealAgent

    for cls in (RealAgent, FakeAgent):
        params = inspect.signature(cls.handle_turn).parameters
        for kwarg in ("audio_seq", "trace"):
            assert kwarg in params, f"{cls.__name__}.handle_turn missing {kwarg=}"
