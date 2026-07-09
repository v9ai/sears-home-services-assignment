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


def test_stt_openai_pins_english_by_default(monkeypatch):
    """Regression (live call 62f77f71…, 2026-07-09): the pre-port OpenAITranscriber honored
    OPENAI_STT_LANGUAGE to stop foreign-language hallucinations on short/near-silent clips,
    but the Pipecat port dropped it — an Arabic turn (`أهلا بك.`) landed in a real English
    call. The factory must pin the language hint (default en) on the service settings."""
    pytest.importorskip("pipecat.services.openai.stt")
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("OPENAI_STT_LANGUAGE", raising=False)  # unset → default "en"

    assert _build_stt()._settings.language == "en"


def test_stt_openai_language_override_and_blank_fallback(monkeypatch):
    pytest.importorskip("pipecat.services.openai.stt")
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-build")

    monkeypatch.setenv("OPENAI_STT_LANGUAGE", "ro")  # retarget the caller base
    assert _build_stt()._settings.language == "ro"

    # Blank omits the field, which falls back to pipecat's own service default ("en") —
    # there is no true auto-detect through this service; blank just defers to the default.
    monkeypatch.setenv("OPENAI_STT_LANGUAGE", "")
    assert str(_build_stt()._settings.language) == "en"


def test_stt_deepgram_pins_english_by_default(monkeypatch):
    """The English-only pin must cover the DEFAULT provider too, not just the OpenAI branch:
    the agent is English-only by design (specs/constitution/mission.md non-goals), so the
    Deepgram build passes language=en-US (BCP-47) unless overridden."""
    pytest.importorskip("pipecat.services.deepgram.stt")
    monkeypatch.delenv("STT_PROVIDER", raising=False)  # unset → default
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("DEEPGRAM_STT_LANGUAGE", raising=False)  # unset → default "en-US"

    assert _build_stt()._settings.language == "en-US"


def test_stt_deepgram_language_override_and_blank_omits(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.stt")
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-used-no-network-at-build")

    monkeypatch.setenv("DEEPGRAM_STT_LANGUAGE", "en-GB")
    assert _build_stt()._settings.language == "en-GB"

    # Blank omits the field, which falls back to pipecat's own service default (Language.EN —
    # the service resolves an unset language to English internally, same story as the OpenAI
    # branch: there is no true auto-detect through this service; blank just defers).
    monkeypatch.setenv("DEEPGRAM_STT_LANGUAGE", "")
    language = _build_stt()._settings.language
    assert getattr(language, "value", language) == "en"


def test_stt_provider_cartesia_selects_cartesia_stt(monkeypatch):
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("CARTESIA_STT_MODEL", raising=False)  # unset → default

    stt = _build_stt()
    assert type(stt).__name__ == "CartesiaSTTService"
    assert stt._settings.model == "ink-whisper"


def test_stt_cartesia_pins_english_by_default(monkeypatch):
    """ink-whisper is Whisper-family, so it shares the foreign-language hallucination habit
    the OpenAI branch pins against — the Cartesia build must pass language=en by default."""
    pytest.importorskip("pipecat.services.cartesia.stt")
    monkeypatch.setenv("STT_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("CARTESIA_STT_LANGUAGE", raising=False)  # unset → default "en"

    assert _build_stt()._settings.language == "en"


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
