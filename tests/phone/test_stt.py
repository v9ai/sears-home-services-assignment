"""STT wrapper unit tests -- exercised against a fake OpenAI client, never the network."""

import wave
from io import BytesIO

import pytest

from app.phone.stt import OpenAITranscriber, pcm16_to_wav_bytes


def test_pcm16_to_wav_bytes_is_a_valid_mono_16bit_wav():
    pcm = b"\x01\x02" * 100
    wav_bytes = pcm16_to_wav_bytes(pcm, 8000)
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 8000
        assert wav_file.readframes(wav_file.getnframes()) == pcm


class _FakeTranscriptions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs

        class _Result:
            pass

        result = _Result()
        result.text = self.text
        return result


class _FakeAudio:
    def __init__(self, text: str) -> None:
        self.transcriptions = _FakeTranscriptions(text)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.audio = _FakeAudio(text)


@pytest.mark.asyncio
async def test_transcribe_returns_stripped_text_from_client():
    client = _FakeClient("  my dryer is squeaking  ")
    transcriber = OpenAITranscriber(client=client, model="gpt-4o-transcribe")
    text = await transcriber.transcribe(b"\x00\x01" * 100, 8000)
    assert text == "my dryer is squeaking"
    assert client.audio.transcriptions.last_kwargs["model"] == "gpt-4o-transcribe"


@pytest.mark.asyncio
async def test_transcribe_empty_audio_short_circuits_without_calling_client():
    client = _FakeClient("should not be reached")
    transcriber = OpenAITranscriber(client=client)
    text = await transcriber.transcribe(b"", 8000)
    assert text == ""
    assert client.audio.transcriptions.last_kwargs is None


def test_model_selection_honors_fallback_env_flag(monkeypatch):
    monkeypatch.delenv("OPENAI_STT_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_STT_USE_FALLBACK", "true")
    transcriber = OpenAITranscriber()
    assert transcriber._model == "whisper-1"


def test_model_selection_defaults_to_gpt4o_transcribe(monkeypatch):
    monkeypatch.delenv("OPENAI_STT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_STT_USE_FALLBACK", raising=False)
    transcriber = OpenAITranscriber()
    assert transcriber._model == "gpt-4o-transcribe"
