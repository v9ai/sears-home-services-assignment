"""Regression tests for the Twilio call-audio sample-rate bug, plus provider-selection tests
for the voice TTS factory (`app.voice.bot._build_tts`).

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

Cartesia (the default TTS provider) is the opposite case: its websocket handshake accepts an
explicit sample rate, and when none is passed it self-adapts to the pipeline's rate instead of
being pinned to a fixed native rate — so under the same 8 kHz Twilio pipeline it must resolve
to 8 kHz, not 24 kHz. `test_cartesia_tts_resolves_to_transport_rate_under_8khz_pipeline` pins
that behavior so a future change can't silently reintroduce an OpenAI-style rate mismatch.

The remaining tests below cover the two branches of `_build_tts` not yet pinned above: the
`deepgram` provider (voice selection/override) and the fail-fast contract for `cartesia` /
`deepgram` (a missing `*_API_KEY` or `CARTESIA_VOICE_ID` raises `KeyError` from the direct
`os.environ[...]` lookup rather than silently degrading).
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


async def _noop_connect_websocket(self):
    """Stub for CartesiaTTSService._connect_websocket — skips the real network handshake."""


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


def test_tts_defaults_to_cartesia(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.tts")
    monkeypatch.delenv("TTS_PROVIDER", raising=False)  # unset → default
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice-not-used-no-network-at-build")

    tts = _build_tts()
    assert type(tts).__name__ == "CartesiaTTSService"


async def test_cartesia_tts_resolves_to_transport_rate_under_8khz_pipeline(monkeypatch):
    """Unlike OpenAI's fixed-24kHz TTS above, Cartesia's websocket handshake accepts an
    explicit sample rate and self-adapts to the pipeline's rate when none is passed — so the
    real service, started under the 8 kHz Twilio pipeline, must resolve to 8 kHz.

    Unlike OpenAITTSService (HTTP, lazy-connects on the first `run_tts` call — never fires
    here since no TextFrame is sent), CartesiaTTSService is a WebsocketTTSService that
    connects eagerly from `start()`. Stub out `_connect_websocket` (the actual network call)
    so this stays hermetic instead of depending on a real Cartesia server being reachable.
    `self.sample_rate` is resolved in the base `TTSService.start()` before `_connect_websocket`
    is ever reached, so stubbing the connect doesn't affect what's under test."""
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-start")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice-not-used-no-network-at-start")

    tts = _build_tts()
    assert type(tts).__name__ == "CartesiaTTSService"
    monkeypatch.setattr(type(tts), "_connect_websocket", _noop_connect_websocket)

    await run_test(
        Pipeline([tts]),
        frames_to_send=[],
        expected_down_frames=[],
        pipeline_params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
        ),
    )

    assert tts.sample_rate == TWILIO_SAMPLE_RATE  # self-adapted to 8 kHz, not pinned to 24 kHz


def test_tts_provider_deepgram_selects_deepgram_tts(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.tts")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("DEEPGRAM_AURA_VOICE", raising=False)  # unset → default

    tts = _build_tts()
    assert type(tts).__name__ == "DeepgramTTSService"
    assert tts._settings.voice == "aura-2-thalia-en"


def test_tts_provider_deepgram_voice_override(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.tts")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("DEEPGRAM_AURA_VOICE", "aura-2-luna-en")

    tts = _build_tts()
    assert tts._settings.voice == "aura-2-luna-en"


def test_tts_provider_deepgram_missing_api_key_raises(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.tts")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_tts()


def test_tts_provider_cartesia_missing_voice_id_raises(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.tts")
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("CARTESIA_VOICE_ID", raising=False)

    with pytest.raises(KeyError):
        _build_tts()


def test_tts_provider_cartesia_missing_api_key_raises(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.tts")
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice-not-used-no-network-at-build")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_tts()
