"""Provider-selection tests for the voice STT factory (`app.voice.bot._build_stt`).

Deepgram streaming STT is the default (it finalizes at end-of-speech, the first-audio
latency win over OpenAI's buffered gpt-4o-transcribe); `STT_PROVIDER=openai` swaps back, and
`STT_PROVIDER=cartesia` swaps to Cartesia's Live STT (`ink-whisper`). These pin that wiring so
a future refactor can't silently flip the default or drop a branch, plus the fail-fast
contract (a missing `*_API_KEY` raises `KeyError` from the direct `os.environ[...]` lookup
rather than silently degrading). Skips cleanly when pipecat / the provider SDK isn't installed
(same contract as the rest of `tests/voice`)."""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat.frames.frames")

from app.voice.bot import _build_stt  # noqa: E402


def test_stt_defaults_to_deepgram(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.stt")
    monkeypatch.delenv("STT_PROVIDER", raising=False)  # unset → default
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-used-no-network-at-build")

    stt = _build_stt()
    assert type(stt).__name__ == "DeepgramSTTService"


def test_stt_provider_openai_selects_openai(monkeypatch):
    pytest.importorskip("pipecat.services.openai.stt")
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-build")

    stt = _build_stt()
    assert type(stt).__name__ == "OpenAISTTService"


def test_stt_provider_cartesia_selects_cartesia_stt(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("CARTESIA_STT_MODEL", raising=False)  # unset → default

    stt = _build_stt()
    assert type(stt).__name__ == "CartesiaSTTService"
    assert stt._settings.model == "ink-whisper"


def test_stt_provider_cartesia_model_override(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("CARTESIA_STT_MODEL", "ink-whisper-large")

    stt = _build_stt()
    assert stt._settings.model == "ink-whisper-large"


def test_stt_deepgram_missing_api_key_raises(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.stt")
    monkeypatch.delenv("STT_PROVIDER", raising=False)  # default: deepgram
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_stt()


def test_stt_cartesia_missing_api_key_raises(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_stt()
