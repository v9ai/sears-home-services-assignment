"""Unit tests for `VoiceMetricsObserver` (`app/voice/metrics.py`) — synthetic frames
only, no network, no pipeline. Covers the end-of-speech -> first-audio latency timer,
the frame.id dedup (a pushed frame is seen once per processor hop it crosses), and
`MetricsFrame` -> structured-event logging.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import (  # noqa: E402
    MetricsFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData  # noqa: E402
from pipecat.observers.base_observer import FramePushed  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

from app.phone.latency import LatencyRecorder  # noqa: E402
from app.voice.metrics import VoiceMetricsObserver  # noqa: E402


def _pushed(frame) -> FramePushed:
    return FramePushed(
        source=None, destination=None, frame=frame, direction=FrameDirection.DOWNSTREAM, timestamp=0
    )


async def test_records_one_sample_from_stop_to_tts_started():
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    await asyncio.sleep(0.05)
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert len(recorder.samples) == 1
    assert recorder.samples[0] >= 0.05


async def test_vad_stop_frame_also_starts_the_timer():
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert len(recorder.samples) == 1


async def test_duplicate_frame_instance_is_deduped_by_id():
    """A pushed frame is seen once per processor-to-processor hop it crosses — the
    SAME TTSStartedFrame instance must only close the timer once, not once per hop."""
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    tts_started = TTSStartedFrame(context_id="c")
    await observer.on_push_frame(_pushed(tts_started))
    await observer.on_push_frame(_pushed(tts_started))  # same instance, second hop

    assert len(recorder.samples) == 1


async def test_metrics_frame_logs_ttfb_event(caplog):
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    metrics_frame = MetricsFrame(data=[TTFBMetricsData(processor="tts", value=0.4)])
    with caplog.at_level(logging.INFO, logger="app.voice.metrics"):
        await observer.on_push_frame(_pushed(metrics_frame))

    assert "event=voice.metrics.ttfb" in caplog.text
    assert "processor=tts" in caplog.text
    assert len(recorder.samples) == 0  # MetricsFrame doesn't affect the latency timer


# --- correctness fixes (2026-07-09 latency-centralization) ----------------------------


async def test_uses_monotonic_clock(monkeypatch):
    """A wall-clock step (NTP adjust) between end-of-speech and first TTS must not
    corrupt the sample — the observer must time via time.monotonic()."""
    import app.voice.metrics as metrics_mod

    fake_now = {"monotonic": 1000.0, "wall": 5_000_000.0}
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: fake_now["monotonic"])
    monkeypatch.setattr(metrics_mod.time, "time", lambda: fake_now["wall"])

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    fake_now["monotonic"] += 1.5
    fake_now["wall"] -= 3600.0  # wall clock jumps back an hour — must be irrelevant
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert recorder.samples == [1.5]


async def test_two_turns_two_independent_samples(monkeypatch):
    import app.voice.metrics as metrics_mod

    fake_now = {"monotonic": 0.0}
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: fake_now["monotonic"])

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    fake_now["monotonic"] += 1.0
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="a")))

    fake_now["monotonic"] += 10.0  # inter-turn gap must not leak into the next sample
    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    fake_now["monotonic"] += 2.0
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="b")))

    assert recorder.samples == [1.0, 2.0]


async def test_user_resuming_speech_resets_timer(monkeypatch):
    """Caller pauses (VAD stop), resumes, then really finishes: latency must be
    measured from the LAST end-of-speech, not the first pause."""
    import app.voice.metrics as metrics_mod

    fake_now = {"monotonic": 0.0}
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: fake_now["monotonic"])

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))  # pause
    fake_now["monotonic"] += 5.0
    await observer.on_push_frame(_pushed(VADUserStartedSpeakingFrame()))  # resumes
    fake_now["monotonic"] += 3.0
    await observer.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))  # real eos
    fake_now["monotonic"] += 0.8
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert recorder.samples == pytest.approx([0.8])  # NOT 8.8 from the first pause


async def test_abandoned_turn_does_not_leak_into_next(monkeypatch):
    """A turn that never reaches TTS (safety-gated/aborted) must not inflate the next
    turn's sample — the stale timer is discarded when the user speaks again."""
    import app.voice.metrics as metrics_mod

    fake_now = {"monotonic": 0.0}
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: fake_now["monotonic"])

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))  # turn 1: no TTS ever
    fake_now["monotonic"] += 30.0
    await observer.on_push_frame(_pushed(UserStartedSpeakingFrame()))  # turn 2 starts
    fake_now["monotonic"] += 2.0
    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    fake_now["monotonic"] += 1.2
    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert recorder.samples == pytest.approx([1.2])  # NOT 33.2 from the abandoned turn


async def test_tts_started_without_prior_stop_is_ignored():
    """The greeting's TTS fires before any user speech — no sample, no crash."""
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="greeting")))

    assert recorder.samples == []


async def test_seen_frame_ids_bounded_by_type_filter():
    """The per-call audio flood (~50 frames/s) must never enter the dedup set —
    only tracked frame types are remembered (bounded memory over long calls)."""
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    for _ in range(500):
        frame = TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=8000, num_channels=1)
        await observer.on_push_frame(_pushed(frame))

    assert len(observer._seen_frame_ids) == 0

    await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
    assert len(observer._seen_frame_ids) == 1  # tracked types still dedup


async def test_over_budget_sample_logs_within_budget_false(monkeypatch, caplog):
    import app.voice.metrics as metrics_mod

    fake_now = {"monotonic": 0.0}
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: fake_now["monotonic"])

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    with caplog.at_level(logging.INFO, logger="app.voice.metrics"):
        await observer.on_push_frame(_pushed(UserStoppedSpeakingFrame()))
        fake_now["monotonic"] += 4.5  # past the phone p95 budget
        await observer.on_push_frame(_pushed(TTSStartedFrame(context_id="c")))

    assert recorder.samples == [4.5]
    assert "event=voice.metrics.latency" in caplog.text
    assert "within_budget=false" in caplog.text  # log_event renders JSON-style booleans
