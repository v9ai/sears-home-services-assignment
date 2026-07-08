"""SpeechPipeline regression guards (latency-engineering § Regression-proof tests).

Guards the measured 75% root cause: serialized per-sentence TTS and the inline-await
backpressure on the agent event stream. All fake-based; no network.
"""

from __future__ import annotations

import asyncio
import time

from app.agent.tts_pipeline import SpeechPipeline

SYNTH_DELAY = 0.2


def make_synth(delay: float, log: list | None = None):
    async def synth(text: str):
        if log is not None:
            log.append(("start", text, time.monotonic()))
        await asyncio.sleep(delay)
        if log is not None:
            log.append(("end", text, time.monotonic()))
        yield f"audio:{text}".encode()

    return synth


async def test_pipeline_parallelism_beats_serial_and_preserves_order():
    """3 × 200 ms sentences must finish in well under the 600 ms serial time,
    with sentence N+1's synthesis starting before N's ends — order preserved."""
    log: list = []
    emitted: list[tuple[int, bytes]] = []

    async def emit(idx: int, text: str, chunk: bytes) -> None:
        emitted.append((idx, chunk))

    pipeline = SpeechPipeline(make_synth(SYNTH_DELAY, log), emit, lookahead=2)
    t0 = time.monotonic()
    for s in ("one", "two", "three"):
        pipeline.feed(s)
    ok = await pipeline.drain()
    wall = time.monotonic() - t0

    assert ok
    assert wall < SYNTH_DELAY * 3 * 0.8, f"no overlap: wall={wall:.2f}s vs serial 0.6s"
    starts = {t: ts for kind, t, ts in log if kind == "start"}
    ends = {t: ts for kind, t, ts in log if kind == "end"}
    assert starts["two"] < ends["one"], "sentence 2 synthesis did not overlap sentence 1"
    assert [i for i, _ in emitted] == sorted(i for i, _ in emitted), "emission out of order"


async def test_feed_never_blocks_on_synthesis():
    """The backpressure guard: feeding all sentences must be near-instant even with
    slow synthesis — the agent event loop must never wait on TTS."""

    async def emit(idx: int, text: str, chunk: bytes) -> None:
        pass

    pipeline = SpeechPipeline(make_synth(0.5), emit, lookahead=2)
    t0 = time.monotonic()
    for s in ("a", "b", "c", "d"):
        pipeline.feed(s)
    feed_wall = time.monotonic() - t0
    await pipeline.drain()
    assert feed_wall < 0.05, f"feed() blocked for {feed_wall:.3f}s — backpressure regression"


async def test_synth_failure_is_contained():
    """One failing sentence must not kill the pipeline or drop later sentences."""
    calls: list[int] = []

    async def synth(text: str):
        if text == "boom":
            raise RuntimeError("synth down")
        await asyncio.sleep(0.01)
        yield b"ok"

    async def emit(idx: int, text: str, chunk: bytes) -> None:
        calls.append(idx)

    pipeline = SpeechPipeline(synth, emit, lookahead=2)
    for s in ("fine", "boom", "also-fine"):
        pipeline.feed(s)
    ok = await pipeline.drain()
    assert not ok  # failure reported
    assert calls == [0, 2]  # sentence 1 skipped, order otherwise intact


async def test_pipeline_overhead_floor():
    """The structural 'never again' guard: with a pinned 550 ms first-chunk synth,
    first emission must land within 550 ms + 150 ms pipeline overhead budget."""
    emitted_at: list[float] = []

    async def synth(text: str):
        await asyncio.sleep(0.55)
        yield b"first"

    async def emit(idx: int, text: str, chunk: bytes) -> None:
        emitted_at.append(time.monotonic())

    pipeline = SpeechPipeline(synth, emit, lookahead=2)
    t0 = time.monotonic()
    pipeline.feed("only sentence")
    await pipeline.drain()
    first_audio = emitted_at[0] - t0
    assert first_audio <= 0.55 + 0.15, (
        f"pipeline overhead {first_audio - 0.55:.3f}s exceeds the 150 ms floor budget — "
        "serialization/inline-await/sync-IO reintroduced somewhere on the path"
    )
