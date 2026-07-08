"""Streamed OpenAI TTS client (`gpt-4o-mini-tts`, tech-stack.md → Models).

A thin wrapper so `app/ws/routes.py` and tests don't touch the OpenAI SDK directly —
tests inject a fake `synthesize` to avoid real network/API-key dependence.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from openai import AsyncOpenAI

WARM_VOICE_INSTRUCTIONS = (
    "Warm, friendly service-agent tone: calm, reassuring, and clear. Speak at a "
    "measured, natural pace, like a helpful appliance technician on the phone."
)


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set (see .env.example).")
    return AsyncOpenAI(api_key=api_key)


async def synthesize(
    text: str,
    *,
    voice: str = "alloy",
    response_format: str = "mp3",
) -> AsyncIterator[bytes]:
    """Stream TTS audio bytes for ``text`` as they arrive from OpenAI."""
    if not text.strip():
        return
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    client = _client()
    async with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        response_format=response_format,
        instructions=WARM_VOICE_INSTRUCTIONS,
    ) as response:
        async for chunk in response.iter_bytes():
            if chunk:
                yield chunk
