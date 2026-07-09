"""End-of-speech -> first-audio latency + per-service metrics for the voice pipeline.

`app/voice/bot.py` already sets `PipelineParams(enable_metrics=True,
enable_usage_metrics=True)`, so Pipecat emits `MetricsFrame`s (TTFB, TTS/LLM usage)
internally — but nothing previously consumed or logged them, and nothing measured
end-of-speech -> first-audio latency for phone calls at all (the pre-port equivalent,
`app/phone/latency.py`'s `LatencyRecorder`, was wired into the deleted `app/phone/`
bridge). `VoiceMetricsObserver` is an observer (not a pipeline-stage `FrameProcessor`)
so it sees every frame pipeline-wide via `on_push_frame` without needing a specific
position in `build_pipeline_task`'s processor list.

Timing key: the turn's LAST `VADUserStoppedSpeakingFrame`/`UserStoppedSpeakingFrame`
(a start-speaking frame re-arms the timer, so a caller who resumes mid-pause — or a
turn that never reached TTS — never inflates the next sample) -> first
`TTSStartedFrame`. Both are emitted independent of a real output transport (a
`TTSService` pushes `TTSStartedFrame` itself before the first audio chunk), so this
works identically in production and in a transport-less `pipecat.tests.utils.run_test`.
Pipecat's own `UserBotLatencyObserver` was considered and rejected: it keys off
`BotStartedSpeakingFrame`, which only a real output transport ever emits, which would
force every latency test through a mocked transport for no benefit.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pipecat.frames.frames import (
    MetricsFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    TTFAMetricsData,
    TTFBMetricsData,
    TTSUsageMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from app.obs import log_event

if TYPE_CHECKING:
    # Deferred: `app.phone.latency` is a submodule of `app.phone`, whose __init__
    # imports app.voice.routes -> app.voice.bot -> app.voice.metrics — importing it at
    # module level here would be a circular import whenever app.voice.bot is imported
    # directly (e.g. from tests) before app.phone has been loaded via some other path.
    # `from __future__ import annotations` keeps this a lazy string annotation.
    from app.phone.latency import LatencyRecorder

logger = logging.getLogger("app.voice.metrics")

# The only frame types the observer acts on. Checked BEFORE the frame-id dedup set so
# the per-call audio flood (~50 frames/s) never enters `_seen_frame_ids` — residual set
# growth is one id per turn event / metrics frame, negligible for any call length.
_TRACKED_FRAMES = (
    VADUserStartedSpeakingFrame,
    UserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStoppedSpeakingFrame,
    TTSStartedFrame,
    MetricsFrame,
)


class VoiceMetricsObserver(BaseObserver):
    """Records per-turn end-of-speech -> first-audio latency and logs Pipecat's own
    per-service metrics (TTFB, TTS/LLM usage) as structured events."""

    def __init__(self, recorder: LatencyRecorder, **kwargs) -> None:
        super().__init__(**kwargs)
        self._recorder = recorder
        self._end_of_speech_time: float | None = None
        self._seen_frame_ids: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        # Type-filter first: untracked frames (the per-call audio flood among them) are
        # ignored outright and never enter the dedup set (bounded memory over long calls).
        if not isinstance(frame, _TRACKED_FRAMES):
            return
        # A pushed frame is seen once per processor-to-processor hop it crosses (e.g.
        # one MetricsFrame is seen many times as it propagates downstream) — dedup by
        # id or the end-of-speech timestamp gets overwritten mid-turn and every metric
        # gets logged once per hop instead of once per frame.
        if frame.id in self._seen_frame_ids:
            return
        self._seen_frame_ids.add(frame.id)

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            # The caller is speaking again: any armed timer is stale — either they
            # resumed after a pause (measure from their LAST stop, not the first) or the
            # previous turn never produced TTS (aborted/gated) and must not leak into
            # this one.
            self._end_of_speech_time = None
        elif isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            if self._end_of_speech_time is None:
                self._end_of_speech_time = time.monotonic()
        elif isinstance(frame, TTSStartedFrame) and self._end_of_speech_time is not None:
            elapsed = time.monotonic() - self._end_of_speech_time
            self._end_of_speech_time = None
            self._recorder.record(elapsed)
            log_event(
                logger,
                "voice.metrics.latency",
                elapsed_s=elapsed,
                within_budget=self._recorder.within_budget(),
            )
        elif isinstance(frame, MetricsFrame):
            for metric in frame.data:
                self._log_metric(metric)

    def _log_metric(self, metric) -> None:  # noqa: ANN001 — pipecat.metrics.metrics.MetricsData
        if isinstance(metric, TTFBMetricsData):
            log_event(
                logger,
                "voice.metrics.ttfb",
                processor=metric.processor,
                value_ms=metric.value * 1000,
            )
        elif isinstance(metric, TTFAMetricsData):
            log_event(
                logger,
                "voice.metrics.ttfa",
                processor=metric.processor,
                value_ms=metric.ttfa * 1000,
            )
        elif isinstance(metric, LLMUsageMetricsData):
            log_event(
                logger,
                "voice.metrics.llm_usage",
                processor=metric.processor,
                prompt_tokens=metric.value.prompt_tokens,
                completion_tokens=metric.value.completion_tokens,
            )
        elif isinstance(metric, TTSUsageMetricsData):
            log_event(
                logger,
                "voice.metrics.tts_usage",
                processor=metric.processor,
                characters=metric.value,
            )
