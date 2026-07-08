"""Bridge unit test (validation.md): a scripted ``start``/``media``/``stop`` sequence
creates a ``channel='phone'`` session and produces outbound ``media`` frames.

Drives ``handle_twilio_media_stream`` directly against a fake WebSocket -- no real
network/ASGI layer needed -- with a fake transcriber and ``FakeAgent`` per the stub
seam (COORDINATION.md §4).
"""

import base64
import math
import struct

import pytest
from fastapi import WebSocketDisconnect

from app.phone.call_context import PhoneCallContext
from app.phone.fake_agent import FakeAgent
from app.phone.routes import handle_twilio_media_stream
from app.phone.vad import FRAME_MS

FRAME_SAMPLES = 8000 * FRAME_MS // 1000


def _tone_mulaw_b64(freq_hz: float = 300.0, amplitude: int = 12000) -> str:
    from app.phone.codec import pcm16_to_mulaw

    tone = [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / 8000)) for i in range(FRAME_SAMPLES)
    ]
    pcm = struct.pack(f"<{FRAME_SAMPLES}h", *tone)
    return base64.b64encode(pcm16_to_mulaw(pcm)).decode("ascii")


def _silence_mulaw_b64() -> str:
    return base64.b64encode(b"\xff" * FRAME_SAMPLES).decode("ascii")


class FakeTwilioWebSocket:
    """Feeds a scripted list of inbound Twilio events; records outbound ``send_json``."""

    def __init__(self, inbound: list[dict]) -> None:
        self._inbound = list(inbound)
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict:
        if not self._inbound:
            raise WebSocketDisconnect()
        return self._inbound.pop(0)

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> str:
        self.calls += 1
        return self.text


class RecordingSessionRecorder:
    def __init__(self) -> None:
        self.started: list[PhoneCallContext] = []
        self.ended: list[str] = []

    async def start_session(self, context: PhoneCallContext) -> str:
        context.session_id = context.call_sid
        self.started.append(context)
        return context.session_id

    async def end_session(self, session_id: str) -> None:
        self.ended.append(session_id)


def _script() -> list[dict]:
    events: list[dict] = [
        {
            "event": "start",
            "start": {
                "callSid": "CA123",
                "streamSid": "MZ456",
                "customParameters": {"From": "+15551234567", "To": "+13186468479"},
            },
        }
    ]
    # A little leading silence, then ~10 frames (200ms) of "speech", then enough
    # trailing silence (300ms hangover = 15 frames) to close the turn.
    for _ in range(3):
        events.append({"event": "media", "media": {"payload": _silence_mulaw_b64()}})
    for _ in range(10):
        events.append({"event": "media", "media": {"payload": _tone_mulaw_b64()}})
    for _ in range(15):
        events.append({"event": "media", "media": {"payload": _silence_mulaw_b64()}})
    events.append({"event": "stop"})
    return events


@pytest.mark.asyncio
async def test_scripted_call_creates_phone_session_and_emits_reply_audio():
    ws = FakeTwilioWebSocket(_script())
    transcriber = FakeTranscriber("my refrigerator stopped cooling yesterday")
    recorder = RecordingSessionRecorder()
    agent = FakeAgent(scripted_replies=["Let's check the condenser coils."])

    bridge = await handle_twilio_media_stream(
        ws,
        agent_factory=lambda: agent,
        transcriber=transcriber,
        session_recorder=recorder,
    )

    assert ws.accepted is True

    # channel='phone' session created with caller number captured.
    assert len(recorder.started) == 1
    ctx = recorder.started[0]
    assert ctx.channel == "phone"
    assert ctx.call_sid == "CA123"
    assert ctx.caller_number == "+15551234567"
    assert ctx.called_number == "+13186468479"
    assert recorder.ended == ["CA123"]

    # STT ran on the closed turn and fed the agent.
    assert transcriber.calls == 1
    assert ("user", "my refrigerator stopped cooling yesterday") in bridge.transcript
    assert ("agent", "Let's check the condenser coils.") in bridge.transcript

    # Outbound media frames for the agent's reply were produced.
    await_media = [m for m in ws.sent if m["event"] == "media"]
    assert len(await_media) > 0
    assert all(m["streamSid"] == "MZ456" for m in await_media)


@pytest.mark.asyncio
async def test_closed_turn_writes_caller_wav_and_passes_audio_seq(monkeypatch, tmp_path):
    from app.phone import routes as phone_routes

    monkeypatch.setattr(phone_routes, "RECORDINGS_DIR", str(tmp_path))

    class CapturingAgent(FakeAgent):
        def __init__(self) -> None:
            super().__init__(scripted_replies=["Let's check the condenser coils."])
            self.received_audio_seq: list[int | None] = []

        async def handle_turn(self, text, bridge, *, audio_seq=None, trace=None) -> None:
            self.received_audio_seq.append(audio_seq)
            await super().handle_turn(text, bridge, audio_seq=audio_seq, trace=trace)

    ws = FakeTwilioWebSocket(_script())
    transcriber = FakeTranscriber("my refrigerator stopped cooling yesterday")
    recorder = RecordingSessionRecorder()
    agent = CapturingAgent()

    await handle_twilio_media_stream(
        ws,
        agent_factory=lambda: agent,
        transcriber=transcriber,
        session_recorder=recorder,
    )

    session_id = recorder.started[0].session_id
    assert agent.received_audio_seq == [1]
    wav_path = tmp_path / session_id / "00001.wav"
    assert wav_path.exists()
    assert wav_path.read_bytes().startswith(b"RIFF")


@pytest.mark.asyncio
async def test_recording_write_failure_does_not_break_the_call(monkeypatch, tmp_path):
    from app.phone import routes as phone_routes

    monkeypatch.setattr(phone_routes, "RECORDINGS_DIR", str(tmp_path))

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)

    ws = FakeTwilioWebSocket(_script())
    transcriber = FakeTranscriber("my refrigerator stopped cooling yesterday")
    recorder = RecordingSessionRecorder()
    agent = FakeAgent(scripted_replies=["Let's check the condenser coils."])

    bridge = await handle_twilio_media_stream(
        ws,
        agent_factory=lambda: agent,
        transcriber=transcriber,
        session_recorder=recorder,
    )

    # The write failure above must not have taken the call down — transcript/audio
    # still flowed normally (spec Decision 5).
    assert ("user", "my refrigerator stopped cooling yesterday") in bridge.transcript
    assert ("agent", "Let's check the condenser coils.") in bridge.transcript
    assert len([m for m in ws.sent if m["event"] == "media"]) > 0


@pytest.mark.asyncio
async def test_call_with_no_speech_never_invokes_transcriber_or_agent():
    events = [
        {
            "event": "start",
            "start": {"callSid": "CA999", "streamSid": "MZ999", "customParameters": {}},
        },
    ]
    for _ in range(20):
        events.append({"event": "media", "media": {"payload": _silence_mulaw_b64()}})
    events.append({"event": "stop"})

    ws = FakeTwilioWebSocket(events)
    transcriber = FakeTranscriber("should never be returned")
    recorder = RecordingSessionRecorder()

    bridge = await handle_twilio_media_stream(
        ws,
        agent_factory=FakeAgent,
        transcriber=transcriber,
        session_recorder=recorder,
    )

    assert transcriber.calls == 0
    assert bridge.transcript == []
    assert recorder.started[0].caller_number is None
