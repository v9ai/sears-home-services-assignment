"""Regression tests for the Twilio call-audio sample-rate bug.

The live symptom was garbled, ~3x-too-slow speech on a real PSTN call. Root cause:
OpenAI's TTS API only ever returns 24 kHz PCM, but `app.voice.bot` runs the transport at
8 kHz (Twilio µ-law) and did not pass an explicit `sample_rate` to `OpenAITTSService`. The
service therefore inherited the StartFrame's 8 kHz and labelled its 24 kHz audio as 8 kHz —
`TTSAudioRawFrame(chunk, self.sample_rate, ...)` in pipecat's `run_tts`. The output transport
then saw "already at the output rate", skipped resampling, and the µ-law encoder shipped raw
24 kHz samples at 8 kHz.

The fix builds the OpenAI TTS at its native 24 kHz (`OPENAI_TTS_SAMPLE_RATE`) so it emits
frames labelled 24 kHz and the output transport resamples them down to 8 kHz for Twilio
(`pipecat.transports.base_output.BaseOutputTransport` resamples `frame.sample_rate` ->
`audio_out_sample_rate`). These tests pin that: the real service, started under an 8 kHz
pipeline, must resolve to 24 kHz — the exact rate used to tag every emitted audio frame.
"""

from __future__ import annotations

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.pipeline.task import PipelineParams  # noqa: E402
from pipecat.tests.utils import run_test  # noqa: E402

from app.voice.bot import (  # noqa: E402
    OPENAI_TTS_SAMPLE_RATE,
    TWILIO_SAMPLE_RATE,
    _build_tts,
)


def test_sample_rate_constants_force_a_resample():
    # The whole point is that TTS runs above the transport rate so the output transport
    # resamples down. If these were ever set equal, the resample path would be skipped and
    # the garbled-audio bug would silently return.
    assert OPENAI_TTS_SAMPLE_RATE == 24000
    assert TWILIO_SAMPLE_RATE == 8000
    assert OPENAI_TTS_SAMPLE_RATE != TWILIO_SAMPLE_RATE


async def test_openai_tts_resolves_to_native_24khz_under_8khz_pipeline(monkeypatch):
    """The real OpenAISTTService, started inside an 8 kHz (Twilio) pipeline, must keep its
    native 24 kHz output rate — that rate is what `run_tts` stamps on every audio frame, so
    24 kHz here is what makes the output transport resample instead of mis-encoding."""
    monkeypatch.setenv("TTS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-start")

    tts = _build_tts()
    assert type(tts).__name__ == "OpenAITTSService"

    # run_test sets up the TaskManager and pushes a StartFrame carrying the pipeline's
    # audio_out_sample_rate; no TextFrame is sent, so run_tts (the only network call) never
    # fires. Starting under 8 kHz is exactly the production condition that triggered the bug.
    await run_test(
        Pipeline([tts]),
        frames_to_send=[],
        expected_down_frames=[],
        pipeline_params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
        ),
    )

    assert tts.sample_rate == OPENAI_TTS_SAMPLE_RATE  # 24 kHz, NOT the 8 kHz StartFrame rate
