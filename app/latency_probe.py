"""`GET /debug/latency-probe` — in-container latency micro-probes (latency O10).

Closes the RCA's one unmeasured number: provider RTT/TTFT *from the hosted
container* (us-east) rather than a developer laptop. Flag-gated
(`LATENCY_PROBE_ENABLED`), read-only, small fixed cost per call (one tiny LLM
completion + one short TTS synth + one SELECT 1). Never mounted unless the flag is
truthy — see `app/main.py`.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.db.base import get_sessionmaker

router = APIRouter()


async def _timed(coro) -> float:
    t0 = time.monotonic()
    await coro
    return round((time.monotonic() - t0) * 1000)


@router.get("/debug/latency-probe")
async def latency_probe() -> dict:
    from openai import AsyncOpenAI

    results: dict[str, object] = {"region_hint": os.environ.get("CF_REGION", "unknown")}
    client = AsyncOpenAI()

    try:
        results["openai_models_ttfb_ms"] = await _timed(client.models.list())
    except Exception as exc:  # noqa: BLE001 — probe reports, never raises
        results["openai_models_ttfb_ms"] = f"error: {type(exc).__name__}"

    try:
        t0 = time.monotonic()
        stream = await client.chat.completions.create(
            model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4.1-mini"),
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2,
            stream=True,
        )
        async for _ in stream:
            break
        results["llm_ttft_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        results["llm_ttft_ms"] = f"error: {type(exc).__name__}"

    try:
        t0 = time.monotonic()
        async with client.audio.speech.with_streaming_response.create(
            model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            voice="alloy",
            input="One moment.",
            response_format="pcm",
        ) as response:
            async for _ in response.iter_bytes():
                break
        results["tts_ttfb_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        results["tts_ttfb_ms"] = f"error: {type(exc).__name__}"

    try:
        factory = get_sessionmaker()
        t0 = time.monotonic()
        async with factory() as db:
            await db.execute(text("SELECT 1"))
        results["db_roundtrip_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        results["db_roundtrip_ms"] = f"error: {type(exc).__name__}"

    return results
