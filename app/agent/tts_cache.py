"""Static audio cache for constant TTS strings (latency-engineering P0-1).

Only the greeting/filler/fallback strings in ``app.agent.fillers.CACHED_STRINGS`` are
cached, synthesized once and played from disk on every subsequent call -- ordinary
LLM-generated sentences pass straight through to ``app.agent.tts.synthesize``
untouched, so this never grows unbounded.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from app.agent import tts
from app.agent.fillers import CACHED_STRINGS

logger = logging.getLogger("app.agent.tts_cache")

CACHE_DIR = Path(os.environ.get("TTS_CACHE_DIR", "data/tts_cache"))


def cache_path(text: str, response_format: str) -> Path:
    digest = hashlib.sha1(text.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.{response_format}"


async def prewarm(formats: tuple[str, ...] = ("pcm",)) -> None:
    """Boot-time warm-up (O1): synthesize every cached constant once so no caller
    ever pays the cold-cache synth. Best-effort; skipped without an API key."""
    if not os.environ.get("OPENAI_API_KEY"):
        return
    for text in CACHED_STRINGS:
        for fmt in formats:
            try:
                if cache_path(text, fmt).exists():
                    continue
                async for _ in synthesize_cached(text, response_format=fmt):
                    pass
            except Exception:  # noqa: BLE001 — warm-up must never break startup
                logger.exception("tts_cache_prewarm_failed")
                return


async def synthesize_cached(
    text: str,
    *,
    voice: str = "alloy",
    response_format: str = "mp3",
) -> AsyncIterator[bytes]:
    """Cache-first wrapper around ``app.agent.tts.synthesize``.

    Text not in ``CACHED_STRINGS`` is a pure passthrough (no disk I/O at all). A
    cached string reads-and-yields the file if present; on a cold cache it streams
    live and best-effort writes the file after -- a write failure is logged, never
    raised, since it must not surface into the turn.
    """
    if text not in CACHED_STRINGS:
        async for chunk in tts.synthesize(text, voice=voice, response_format=response_format):
            yield chunk
        return

    path = cache_path(text, response_format)
    if path.exists():
        yield path.read_bytes()
        return

    buffer = bytearray()
    async for chunk in tts.synthesize(text, voice=voice, response_format=response_format):
        buffer.extend(chunk)
        yield chunk

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(buffer))
    except OSError:
        logger.exception("tts_cache_write_failed path=%s", path)
