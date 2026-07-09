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
    TTSStartedFrame,
    UserStoppedSpeakingFrame,
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
