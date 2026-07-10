"""Streamed web-channel TTS client (tech-stack.md → Models).

Default provider: **Cartesia** for pcm (h2 DECISION, user-approved 2026-07-10,
applied loop v2 i7 after the f3 paired A/B measured Cartesia pcm TTFB p50 223 ms vs
OpenAI 696 ms — 3.1×): pcm requests stream from Cartesia's SSE endpoint, reusing the
same `CARTESIA_API_KEY`/`CARTESIA_VOICE_ID` env the phone path's Pipecat Cartesia
service uses. `WEB_TTS_PROVIDER=openai` swaps back; mp3 requests (legacy blob path)
always use OpenAI `gpt-4o-mini-tts` (Cartesia SSE rejects mp3 — measured 400).

A thin wrapper so `app/ws/routes.py` and tests don't touch provider SDKs directly —
tests inject a fake `synthesize` to avoid real network/API-key dependence.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from functools import lru_cache

from openai import AsyncOpenAI

WARM_VOICE_INSTRUCTIONS = (
    "Warm, friendly service-agent tone: calm, reassuring, and clear. Speak at a "
    "measured, natural pace, like a helpful appliance technician on the phone."
)

CARTESIA_TTS_SSE_URL = "https://api.cartesia.ai/tts/sse"
CARTESIA_VERSION = "2024-06-10"

# response_format -> Cartesia output_format payload. Only "pcm" (the web channel's
# pcm24k frames, O9/O12): Cartesia's SSE endpoint 400s on mp3 (measured 2026-07-10
# A/B), so legacy mp3 requests fall through to OpenAI regardless of provider env.
_CARTESIA_OUTPUT_FORMATS = {
    "pcm": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
}


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set (see .env.example).")
    return AsyncOpenAI(api_key=api_key)


def _parse_sse_audio_chunk(line: str) -> bytes | None:
    """One SSE line -> audio bytes, or None for non-audio lines (done/keepalive).

    Cartesia's SSE stream sends `data: {"type": "chunk", "data": "<b64>", ...}` events
    and a terminal `data: {"type": "done", ...}`. Pure function — offline-testable.
    """
    if not line.startswith("data:"):
        return None
    try:
        payload = json.loads(line[len("data:") :].strip())
    except json.JSONDecodeError:
        return None
    if payload.get("type") == "chunk" and payload.get("data"):
        return base64.b64decode(payload["data"])
    return None


async def _synthesize_cartesia(text: str, *, response_format: str) -> AsyncIterator[bytes]:
    """Stream TTS audio from Cartesia's SSE endpoint (f3 adapter)."""
    import httpx

    api_key = os.environ.get("CARTESIA_API_KEY")
    voice_id = os.environ.get("CARTESIA_VOICE_ID")
    if not api_key or not voice_id:
        raise RuntimeError(
            "WEB_TTS_PROVIDER=cartesia needs CARTESIA_API_KEY and CARTESIA_VOICE_ID "
            "(see .env.example)."
        )
    output_format = _CARTESIA_OUTPUT_FORMATS[response_format]

    body = {
        "model_id": os.environ.get("CARTESIA_TTS_MODEL", "sonic-3.5"),
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": output_format,
        "language": "en",
    }
    headers = {"X-API-Key": api_key, "Cartesia-Version": CARTESIA_VERSION}
    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream("POST", CARTESIA_TTS_SSE_URL, json=body, headers=headers) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            chunk = _parse_sse_audio_chunk(line)
            if chunk:
                yield chunk


async def synthesize(
    text: str,
    *,
    voice: str = "alloy",
    response_format: str = "mp3",
) -> AsyncIterator[bytes]:
    """Stream TTS audio bytes for ``text`` from the configured web provider."""
    if not text.strip():
        return
    # h2 default (user decision 2026-07-10; A/B: 223ms vs 696ms TTFB): cartesia for
    # pcm. WEB_TTS_PROVIDER=openai swaps back; mp3 always falls through to OpenAI.
    provider = os.environ.get("WEB_TTS_PROVIDER", "cartesia").strip().lower()
    if provider == "cartesia" and response_format in _CARTESIA_OUTPUT_FORMATS:
        async for chunk in _synthesize_cartesia(text, response_format=response_format):
            yield chunk
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
