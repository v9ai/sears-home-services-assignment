"""Lifecycle tests for `app/voice/bot.py` — `run_bot` and the transport/recording event
handlers (`_on_connected` / `_on_disconnected` / `_on_audio_data`).

These are the call's start/stop plumbing: the last big uncovered block in bot.py. They're
welded to Pipecat's `FastAPIWebsocketTransport` + `PipelineRunner`, so a live socket can't
run hermetically. Instead:

- `run_bot` is driven with fakes for `FastAPIWebsocketTransport`, `build_pipeline_task`, and
  `PipelineRunner`, so we exercise the real credential check, error safety-net, and the
  end-of-call `twilio.call.summary` without a network or provider keys.
- the three event handlers are captured from a REAL `build_pipeline_task` build (fake
  transport + fake AudioBufferProcessor, injected FakeSTT/LLM/TTS — the same seam
  `tests/voice/test_call_recording.py` already uses) and then invoked directly, with the
  `PipelineTask` and the DB/persist collaborators faked so we observe the side effects.

NOT covered here (needs a live audio pipeline, not faked badly): the actual VAD/STT/LLM/TTS
frame flow through a running `PipelineRunner`, and real µ-law audio buffering inside
`AudioBufferProcessor`. Those live in the e2e/latency lanes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pytest

pytest.importorskip("pipecat.frames.frames")

from pipecat.frames.frames import TTSSpeakFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameProcessor  # noqa: E402

from app.voice import bot as voice_bot  # noqa: E402
from app.voice.bot import GREETING, build_pipeline_task, run_bot  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402

# --- run_bot -----------------------------------------------------------------------------


class _FakeTransport:
    def __init__(self, *, websocket=None, params=None) -> None:
        self.websocket = websocket
        self.params = params
        self.handlers: dict[str, object] = {}

    def input(self) -> FrameProcessor:
        return FrameProcessor()

    def output(self) -> FrameProcessor:
        return FrameProcessor()

    def event_handler(self, name):
        def _decorator(fn):
            self.handlers[name] = fn
            return fn

        return _decorator


class _FakeRecorder:
    samples: list = []
    p50 = 0.0
    p95 = 0.0

    def within_budget(self) -> bool:
        return True


class _FakeTask:
    def __init__(self, *args, **kwargs) -> None:
        self.queued: list = []
        self.cancelled = False

    async def queue_frames(self, frames) -> None:
        self.queued.append(frames)

    async def cancel(self) -> None:
        self.cancelled = True


class _FakeRunner:
    instances: list = []

    def __init__(self, *, handle_sigint=True) -> None:
        self.handle_sigint = handle_sigint
        self.ran = None
        self.raise_on_run = False
        _FakeRunner.instances.append(self)

    async def run(self, task) -> None:
        self.ran = task
        if self.raise_on_run:
            raise RuntimeError("pipeline blew up")


def _install_run_bot_fakes(monkeypatch, *, run_raises: bool = False):
    """Wire run_bot to fakes; returns the captured (task, transport, runner_holder)."""
    captured: dict = {}

    def _fake_build(transport, session, **kwargs):
        task = _FakeTask()
        captured["task"] = task
        captured["session"] = session
        captured["transport"] = transport
        return task, _FakeRecorder()

    class _Runner(_FakeRunner):
        def __init__(self, *, handle_sigint=True) -> None:
            super().__init__(handle_sigint=handle_sigint)
            self.raise_on_run = run_raises

    monkeypatch.setattr(voice_bot, "FastAPIWebsocketTransport", _FakeTransport)
    monkeypatch.setattr(voice_bot, "build_pipeline_task", _fake_build)
    monkeypatch.setattr(voice_bot, "PipelineRunner", _Runner)
    _FakeRunner.instances = []
    return captured


async def test_run_bot_builds_and_runs_the_pipeline(monkeypatch, caplog):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    captured = _install_run_bot_fakes(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await run_bot(object(), stream_sid="MZ1", call_sid="CAlifecycle")

    # session was built for this call and the task was run.
    assert isinstance(captured["session"], VoiceSession)
    assert captured["session"].call_sid == "CAlifecycle"
    assert _FakeRunner.instances[0].ran is captured["task"]
    assert captured["task"].cancelled is False  # happy path: no error cancel
    # end-of-call summary always logged, with the serializer's (zeroed) counters.
    assert "event=twilio.call.summary" in caplog.text
    assert "inbound_frames=0" in caplog.text
    # creds present -> no autohangup-disabled warning.
    assert "autohangup_disabled" not in caplog.text


async def test_run_bot_missing_creds_degrades_gracefully(monkeypatch, caplog):
    """Task #41 fix: missing Twilio creds build the serializer with auto_hang_up=False, so
    the call still runs (hangup skipped) and logs `autohangup_disabled` instead of raising
    ValueError before the pipeline ever starts."""
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    captured = _install_run_bot_fakes(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await run_bot(object(), stream_sid="MZ1", call_sid="CA1")

    assert "event=twilio.serializer.autohangup_disabled" in caplog.text
    assert "reason=missing_twilio_credentials" in caplog.text
    assert "event=twilio.call.summary" in caplog.text  # summary still fires
    assert _FakeRunner.instances[0].ran is captured["task"]  # the call actually ran


async def test_run_bot_error_is_caught_and_task_cancelled(monkeypatch, caplog):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    captured = _install_run_bot_fakes(monkeypatch, run_raises=True)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await run_bot(object(), stream_sid="MZ1", call_sid="CAboom")  # must not raise

    # the safety net logged a sanitized error and cancelled the task...
    assert "event=twilio.pipeline.error" in caplog.text
    assert "error=RuntimeError" in caplog.text
    assert captured["task"].cancelled is True
    # ...and the finally-block summary still ran.
    assert "event=twilio.call.summary" in caplog.text


# --- transport / recording event handlers ------------------------------------------------


class _FakeAudioBuffer(FrameProcessor):
    """Captures its event handlers and records start/stop calls; stands in for
    AudioBufferProcessor so no real audio backend is needed."""

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self.kwargs = kwargs
        self.handlers: dict[str, object] = {}
        self.started = 0
        self.stopped = 0
        self.stop_raises = False

    def event_handler(self, name):
        def _decorator(fn):
            self.handlers[name] = fn
            return fn

        return _decorator

    async def start_recording(self) -> None:
        self.started += 1

    async def stop_recording(self) -> None:
        self.stopped += 1
        if self.stop_raises:
            raise RuntimeError("stop failed")


class _Built:
    """Holds everything a handler test needs after one build_pipeline_task call."""

    def __init__(self, transport, audiobuffer, task, session) -> None:
        self.transport = transport
        self.audiobuffer = audiobuffer
        self.task = task
        self.session = session

    @property
    def on_connected(self):
        return self.transport.handlers["on_client_connected"]

    @property
    def on_disconnected(self):
        return self.transport.handlers["on_client_disconnected"]

    @property
    def on_audio_data(self):
        return self.audiobuffer.handlers["on_audio_data"]


def _build_with_handlers(monkeypatch, *, persist=None, ensure=None) -> _Built:
    monkeypatch.setenv("VOICE_RECORDING_ENABLED", "1")
    audiobuffers: list[_FakeAudioBuffer] = []

    def _make_buffer(**kwargs):
        buf = _FakeAudioBuffer(**kwargs)
        audiobuffers.append(buf)
        return buf

    tasks: list[_FakeTask] = []

    def _make_task(*args, **kwargs):
        task = _FakeTask(*args, **kwargs)
        tasks.append(task)
        return task

    async def _noop_ensure(_session) -> None:
        if ensure is not None:
            ensure.append(_session)

    monkeypatch.setattr(voice_bot, "AudioBufferProcessor", _make_buffer)
    monkeypatch.setattr(voice_bot, "PipelineTask", _make_task)
    monkeypatch.setattr(voice_bot, "ensure_voice_session_row", _noop_ensure)
    if persist is not None:
        monkeypatch.setattr(voice_bot, "persist_voice_session", persist)

    transport = _FakeTransport()
    session = VoiceSession.for_call("CAhandlers")
    build_pipeline_task(transport, session, stt=FakeSTT(), llm=FakeLLM(), tts=FakeTTS())
    return _Built(transport, audiobuffers[0], tasks[0], session)


async def test_on_connected_greets_and_starts_recording(monkeypatch):
    ensured: list = []
    built = _build_with_handlers(monkeypatch, ensure=ensured)

    await built.on_connected(object(), object())
    # _on_connected spawns ensure_voice_session_row via create_task off the greeting path;
    # yield control so that background task runs before we assert on it.
    for _ in range(5):
        if ensured:
            break
        await asyncio.sleep(0)

    # greeting queued as a constant TTSSpeakFrame (no LLM round-trip)...
    assert len(built.task.queued) == 1
    (frame,) = built.task.queued[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == GREETING
    # ...recording armed, and the call-start sessions-row task spawned.
    assert built.audiobuffer.started == 1
    assert ensured == [built.session]  # ensure_voice_session_row(session) ran


async def test_on_disconnected_persists_and_cancels(monkeypatch):
    persisted: list = []

    async def _persist(session, context, started_at, ended_at) -> None:
        persisted.append((session, started_at, ended_at))

    built = _build_with_handlers(monkeypatch, persist=_persist)

    await built.on_connected(object(), object())  # stamps started_at
    await built.on_disconnected(object(), object())

    assert built.audiobuffer.stopped == 1
    assert len(persisted) == 1
    session, started_at, ended_at = persisted[0]
    assert session is built.session
    assert isinstance(started_at, datetime) and started_at.tzinfo is not None
    assert ended_at >= started_at  # the connect timestamp flows into persist
    assert built.task.cancelled is True


async def test_on_disconnected_persist_failure_still_cancels(monkeypatch, caplog):
    async def _boom_persist(*_a, **_k) -> None:
        raise RuntimeError("db down")

    built = _build_with_handlers(monkeypatch, persist=_boom_persist)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await built.on_disconnected(object(), object())  # must not raise

    assert "event=voice.recording.persist_failed" in caplog.text
    assert built.task.cancelled is True  # teardown always cancels the task


async def test_on_disconnected_stop_recording_failure_is_swallowed(monkeypatch, caplog):
    persisted: list = []

    async def _persist(*a, **_k) -> None:
        persisted.append(a)

    built = _build_with_handlers(monkeypatch, persist=_persist)
    built.audiobuffer.stop_raises = True

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await built.on_disconnected(object(), object())

    assert "event=voice.recording.stop_failed" in caplog.text
    assert len(persisted) == 1  # a stop failure doesn't skip persistence
    assert built.task.cancelled is True


async def test_double_disconnect_is_safe(monkeypatch):
    async def _persist(*_a, **_k) -> None:
        pass

    built = _build_with_handlers(monkeypatch, persist=_persist)

    await built.on_disconnected(object(), object())
    await built.on_disconnected(object(), object())  # idempotent, no raise

    assert built.task.cancelled is True


async def test_on_audio_data_writes_stereo_wav(monkeypatch, caplog):
    written: list = []

    def _spy_write(path, audio, sample_rate, num_channels) -> None:
        written.append((path, audio, sample_rate, num_channels))

    monkeypatch.setattr(voice_bot, "write_stereo_wav", _spy_write)
    built = _build_with_handlers(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await built.on_audio_data(object(), b"\x00\x01" * 20, 8000, 2)

    assert len(written) == 1
    path, audio, rate, channels = written[0]
    assert str(built.session.session_id) in path and path.endswith("call.wav")
    assert audio == b"\x00\x01" * 20
    assert (rate, channels) == (8000, 2)
    assert "event=voice.recording.saved" in caplog.text


async def test_on_audio_data_write_failure_is_swallowed(monkeypatch, caplog):
    def _boom_write(*_a, **_k) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(voice_bot, "write_stereo_wav", _boom_write)
    built = _build_with_handlers(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        await built.on_audio_data(object(), b"\x00", 8000, 2)  # must not raise

    assert "event=voice.recording.write_failed" in caplog.text
    assert "error=OSError" in caplog.text
