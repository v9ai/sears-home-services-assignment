"""``TwilioMediaBridge`` unit tests: SessionBridge conformance, playback framing,
barge-in (``clear``), and latency instrumentation.
"""

import asyncio

import pytest

from app.contracts import SessionBridge
from app.phone.bridge import TwilioMediaBridge
from app.phone.codec import MULAW_FRAME_BYTES, decode_b64_frame
from app.phone.fake_agent import FakeAgent


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _media_events(socket: FakeSocket) -> list[dict]:
    return [m for m in socket.sent if m["event"] == "media"]


def _clear_events(socket: FakeSocket) -> list[dict]:
    return [m for m in socket.sent if m["event"] == "clear"]


@pytest.mark.asyncio
async def test_bridge_satisfies_session_bridge_protocol():
    bridge = TwilioMediaBridge(FakeSocket(), FakeAgent())
    assert isinstance(bridge, SessionBridge)


@pytest.mark.asyncio
async def test_emit_audio_frames_as_mulaw_20ms_chunks():
    socket = FakeSocket()
    bridge = TwilioMediaBridge(socket, FakeAgent(), frame_interval_s=0)
    bridge.bind_stream("SS1")

    # 100ms of PCM16 @ 8kHz (no resample needed) -> 5 outbound 20ms mu-law frames.
    pcm = b"\x00\x10" * (8000 * 100 // 1000)
    await bridge.emit_audio(pcm, sample_rate=8000)
    await asyncio.sleep(0)  # let the playback task run to completion

    media = _media_events(socket)
    assert len(media) == 5
    for frame in media:
        assert frame["streamSid"] == "SS1"
        raw = decode_b64_frame(frame["media"]["payload"])
        assert len(raw) == MULAW_FRAME_BYTES
    assert _clear_events(socket) == []  # nothing was playing before -- no barge-in


@pytest.mark.asyncio
async def test_receive_user_utterance_drives_agent_and_records_transcript():
    socket = FakeSocket()
    agent = FakeAgent(scripted_replies=["Sounds like a bad thermostat."])
    bridge = TwilioMediaBridge(socket, agent, frame_interval_s=0)
    bridge.bind_stream("SS1")

    await bridge.receive_user_utterance("my fridge stopped cooling")
    await asyncio.sleep(0)

    assert bridge.transcript == [
        ("user", "my fridge stopped cooling"),
        ("agent", "Sounds like a bad thermostat."),
    ]
    assert len(_media_events(socket)) > 0


@pytest.mark.asyncio
async def test_interrupt_playback_cancels_in_flight_audio_and_sends_clear():
    socket = FakeSocket()
    bridge = TwilioMediaBridge(socket, FakeAgent(), frame_interval_s=0.05)
    bridge.bind_stream("SS1")

    # Several seconds of audio at the frame level so cancellation lands mid-stream.
    pcm = b"\x00\x10" * (8000 * 1)  # 1s -> 50 frames at 20ms/frame
    await bridge.emit_audio(pcm, sample_rate=8000)
    await asyncio.sleep(0.12)  # let ~2 frames go out (0.05s interval each)

    assert bridge.is_playing is True
    frames_before = len(_media_events(socket))
    assert 0 < frames_before < 50

    await bridge.interrupt_playback()

    assert bridge.is_playing is False
    assert len(_clear_events(socket)) == 1
    frames_after_wait = len(_media_events(socket))
    await asyncio.sleep(0.15)  # cancellation must stick -- no further frames trickle out
    assert len(_media_events(socket)) == frames_after_wait


@pytest.mark.asyncio
async def test_emit_audio_while_playing_supersedes_previous_playback():
    socket = FakeSocket()
    bridge = TwilioMediaBridge(socket, FakeAgent(), frame_interval_s=0.05)
    bridge.bind_stream("SS1")

    pcm = b"\x00\x10" * (8000 * 1)
    await bridge.emit_audio(pcm, sample_rate=8000)
    await asyncio.sleep(0.06)

    # A new emit_audio (e.g. a fresh agent turn) should barge in on the old one.
    await bridge.emit_audio(pcm, sample_rate=8000)
    assert len(_clear_events(socket)) == 1
    await asyncio.sleep(0)
    assert bridge.is_playing is True


@pytest.mark.asyncio
async def test_interrupt_playback_is_a_noop_when_idle():
    socket = FakeSocket()
    bridge = TwilioMediaBridge(socket, FakeAgent())
    bridge.bind_stream("SS1")
    await bridge.interrupt_playback()
    # Nothing was playing -- no `clear` needed; avoids spamming Twilio on every
    # routine turn transition (emit_audio calls this unconditionally first).
    assert _clear_events(socket) == []


@pytest.mark.asyncio
async def test_mark_end_of_speech_records_latency_on_first_outbound_frame():
    socket = FakeSocket()
    bridge = TwilioMediaBridge(socket, FakeAgent(), frame_interval_s=0)
    bridge.bind_stream("SS1")

    bridge.mark_end_of_speech()
    await asyncio.sleep(0.01)
    pcm = b"\x00\x10" * (8000 * 20 // 1000)
    await bridge.emit_audio(pcm, sample_rate=8000)
    await asyncio.sleep(0)

    assert len(bridge.latency.samples) == 1
    assert 0 <= bridge.latency.samples[0] < 1.0
