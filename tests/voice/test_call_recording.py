"""Tests for the Pipecat voice-bot full-call recording (`app/voice/recording.py` +
`app/voice/bot.py` wiring). Hermetic — no network, no real transport."""

from __future__ import annotations

import wave

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.processors.frame_processor import FrameProcessor  # noqa: E402

from app.voice.bot import build_pipeline_task  # noqa: E402
from app.voice.recording import (  # noqa: E402
    call_recording_path,
    recording_enabled,
    transcript_from_context,
    write_stereo_wav,
)
from app.voice.session import VoiceSession  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402


# --- write_stereo_wav ---------------------------------------------------------------------
def test_write_stereo_wav_produces_two_channel_wav(tmp_path):
    # 4 stereo PCM16 frames = 16 bytes (2 channels * 2 bytes * 4 frames).
    pcm = b"\x01\x02\x03\x04" * 4
    path = tmp_path / "sess" / "call.wav"

    write_stereo_wav(str(path), pcm, sample_rate=8000, num_channels=2)

    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == 8000
        assert w.getsampwidth() == 2
        assert w.getnframes() == len(pcm) // (2 * 2)  # bytes / (channels * sampwidth)


def test_call_recording_path_is_per_session_call_wav():
    assert call_recording_path("abc").endswith("/abc/call.wav")


# --- transcript_from_context --------------------------------------------------------------
def test_transcript_from_context_filters_and_maps_roles():
    context = LLMContext(messages=[{"role": "system", "content": "SYSTEM PROMPT"}])
    context.add_message({"role": "assistant", "content": "Thanks for calling."})  # greeting
    context.add_message({"role": "user", "content": "my dryer is loud"})
    context.add_message({"role": "assistant", "content": "Sorry to hear that."})
    context.add_message({"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]})
    context.add_message({"role": "tool", "content": "tool result", "tool_call_id": "x"})
    context.add_message({"role": "user", "content": "   "})  # blank -> dropped

    transcript = transcript_from_context(context)

    assert transcript == [
        {"role": "agent", "text": "Thanks for calling."},
        {"role": "user", "text": "my dryer is loud"},
        {"role": "agent", "text": "Sorry to hear that."},
    ]


def test_transcript_collapses_the_double_seeded_greeting():
    """Regression (live call c09dd5b3…): the greeting reaches the context twice — seeded by
    `_on_connected` AND recorded again by the assistant aggregator once TTS speaks it — and
    the persisted transcript showed a doubled first line in the replay UI."""
    greeting = "Thanks for calling Sears Home Services!"
    context = LLMContext(messages=[{"role": "system", "content": "SYS"}])
    context.add_message({"role": "assistant", "content": greeting})  # manual seed
    context.add_message({"role": "assistant", "content": greeting})  # aggregator echo
    context.add_message({"role": "user", "content": "my fridge is blanking"})

    transcript = transcript_from_context(context)

    assert transcript == [
        {"role": "agent", "text": greeting},
        {"role": "user", "text": "my fridge is blanking"},
    ]


def test_transcript_keeps_non_adjacent_repeats():
    """Only *consecutive* duplicates are an artifact; a caller legitimately repeating the
    same words later in the call must be preserved."""
    context = LLMContext(messages=[])
    context.add_message({"role": "user", "content": "it's still broken"})
    context.add_message({"role": "assistant", "content": "Let's try unplugging it."})
    context.add_message({"role": "user", "content": "it's still broken"})  # said again later

    transcript = transcript_from_context(context)

    assert [t["text"] for t in transcript] == [
        "it's still broken",
        "Let's try unplugging it.",
        "it's still broken",
    ]


# --- recording_enabled gate ---------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [(None, True), ("1", True), ("true", True), ("0", False), ("false", False), ("off", False)],
)
def test_recording_enabled_gate(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("VOICE_RECORDING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("VOICE_RECORDING_ENABLED", value)
    assert recording_enabled() is expected


# --- pipeline wiring ----------------------------------------------------------------------
class _FakeTransport:
    """Minimal transport double: build_pipeline_task only needs input()/output() (pipeline
    stages) and event_handler() (a decorator)."""

    def input(self) -> FrameProcessor:
        return FrameProcessor()

    def output(self) -> FrameProcessor:
        return FrameProcessor()

    def event_handler(self, _name):
        def _decorator(fn):
            return fn

        return _decorator


class _SpyAudioBuffer(FrameProcessor):
    """Stands in for AudioBufferProcessor so the test can assert it was (or wasn't) wired,
    without a real transport/audio backend."""

    instances: list = []

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self.kwargs = kwargs
        _SpyAudioBuffer.instances.append(self)

    def event_handler(self, _name):
        def _decorator(fn):
            return fn

        return _decorator


def _build(monkeypatch):
    _SpyAudioBuffer.instances = []
    monkeypatch.setattr("app.voice.bot.AudioBufferProcessor", _SpyAudioBuffer)
    session = VoiceSession.for_call("CAtest")
    build_pipeline_task(_FakeTransport(), session, stt=FakeSTT(), llm=FakeLLM(), tts=FakeTTS())


def test_recorder_wired_when_enabled(monkeypatch):
    monkeypatch.setenv("VOICE_RECORDING_ENABLED", "1")
    _build(monkeypatch)
    assert len(_SpyAudioBuffer.instances) == 1
    assert _SpyAudioBuffer.instances[0].kwargs.get("num_channels") == 2


def test_recorder_absent_when_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_RECORDING_ENABLED", "0")
    _build(monkeypatch)
    assert _SpyAudioBuffer.instances == []
