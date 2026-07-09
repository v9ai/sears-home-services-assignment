"""Provider-selection + sample-rate test for Cartesia STT (`app.voice.bot._build_stt`).

Companion to `test_tts_sample_rate.py`'s Cartesia TTS test: Cartesia's STT websocket
handshake also accepts an explicit sample rate and, when none is passed, self-adapts to the
pipeline's input rate (`frame.audio_in_sample_rate`, per pipecat's `STTService.start`) rather
than being pinned to a fixed rate. Under the 8 kHz Twilio pipeline it must resolve to 8 kHz.
`STT_PROVIDER=deepgram` (the default) and `=openai` are already pinned by
`tests/voice/test_stt_provider.py`; this file only covers the new `cartesia` branch.
"""

from __future__ import annotations

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import STTMetadataFrame  # noqa: E402
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.pipeline.task import PipelineParams  # noqa: E402
from pipecat.tests.utils import run_test  # noqa: E402

from app.voice.bot import TWILIO_SAMPLE_RATE, _build_stt  # noqa: E402


async def _noop_connect_websocket(self):
    """Stub for CartesiaSTTService._connect_websocket — skips the real network handshake."""


def test_stt_provider_cartesia_selects_cartesia(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")

    stt = _build_stt()
    assert type(stt).__name__ == "CartesiaSTTService"


async def test_cartesia_stt_resolves_to_transport_rate_under_8khz_pipeline(monkeypatch):
    """CartesiaSTTService is a WebsocketSTTService that connects eagerly from `start()`
    (unlike Deepgram/OpenAI's STT services in this app, which lazily connect on first audio).
    Stub out `_connect_websocket` (the actual network call) so this stays hermetic instead of
    depending on a real Cartesia server being reachable. `self.sample_rate` is resolved in the
    base `STTService.start()` before `_connect_websocket` is ever reached, so stubbing the
    connect doesn't affect what's under test. The base class also unconditionally broadcasts
    an `STTMetadataFrame` at start — that's the one expected down frame here."""
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-start")

    stt = _build_stt()
    assert type(stt).__name__ == "CartesiaSTTService"
    monkeypatch.setattr(type(stt), "_connect_websocket", _noop_connect_websocket)

    await run_test(
        Pipeline([stt]),
        frames_to_send=[],
        expected_down_frames=[STTMetadataFrame],
        pipeline_params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
        ),
    )

    assert stt.sample_rate == TWILIO_SAMPLE_RATE
