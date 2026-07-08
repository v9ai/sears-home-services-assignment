"""Turn-based STT for the phone channel.

requirements.md: ``gpt-4o-transcribe`` on turn-buffered caller audio (VAD-endpointed
by :mod:`app.phone.vad`); ``whisper-1`` behind an env flag
(``OPENAI_STT_FALLBACK_MODEL`` / ``OPENAI_STT_MODEL``). Turn-based (not the OpenAI
Realtime API -- tech-stack.md forbidden patterns) keeps STT -> agent -> TTS debuggable.

The OpenAI client is injectable so unit/bridge tests never hit the network; see
``FakeTranscriber`` in the test suite for the stub used against fixture audio.
"""

from __future__ import annotations

import io
import os
import wave
from typing import Protocol, runtime_checkable

DEFAULT_STT_MODEL = "gpt-4o-transcribe"
FALLBACK_STT_MODEL = "whisper-1"


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, pcm16: bytes, sample_rate: int) -> str: ...


def pcm16_to_wav_bytes(pcm16: bytes, sample_rate: int) -> bytes:
    """Wrap raw mono PCM16 in a minimal WAV container -- the shape the OpenAI
    transcription endpoint expects as a file upload."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16)
    return buf.getvalue()


class OpenAITranscriber:
    """Transcribes a buffered caller turn via the OpenAI audio transcription API."""

    def __init__(self, client: object | None = None, model: str | None = None) -> None:
        self._client = client
        use_fallback = os.environ.get("OPENAI_STT_USE_FALLBACK", "").lower() in (
            "1",
            "true",
            "yes",
        )
        default_model = FALLBACK_STT_MODEL if use_fallback else DEFAULT_STT_MODEL
        self._model = model or os.environ.get("OPENAI_STT_MODEL", default_model)
        # Language hint. Pinning the expected language stops the Whisper-family
        # habit of hallucinating a foreign language (e.g. Chinese) on short,
        # near-silent clips. Defaults to English for this US home-services line;
        # set OPENAI_STT_LANGUAGE="" to restore auto-detect, or to another
        # ISO-639-1 code (e.g. "ro") for a different caller base.
        self._language = os.environ.get("OPENAI_STT_LANGUAGE", "en").strip() or None

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> str:
        if not pcm16:
            return ""
        client = self._client or self._default_client()
        wav_bytes = pcm16_to_wav_bytes(pcm16, sample_rate)
        kwargs: dict = {}
        if self._language:
            kwargs["language"] = self._language
        result = await client.audio.transcriptions.create(
            model=self._model,
            file=("turn.wav", wav_bytes, "audio/wav"),
            **kwargs,
        )
        text = getattr(result, "text", None) or ""
        return text.strip()

    @staticmethod
    def _default_client():
        from openai import AsyncOpenAI

        return AsyncOpenAI()


def get_transcriber(client: object | None = None) -> Transcriber:
    return OpenAITranscriber(client=client)
