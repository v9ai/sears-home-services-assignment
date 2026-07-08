"""Parallel per-sentence TTS pipeline (latency-engineering P0-3 — the measured 75%).

The RCA showed serialized per-sentence synthesis consumed 11.34 s of a 15.04 s turn:
sentence N+1's synthesis couldn't start until N's finished, and the inline await also
back-pressured `run_turn` event consumption. This helper decouples the three roles:

    producer (caller)  --enqueue text-->  synth workers (lookahead-bounded)
                                              |ordered chunks
                                              v
                                          emitter (caller-supplied)

- Synthesis of up to ``lookahead`` sentences runs concurrently with emission.
- Emission order is strictly the enqueue order (chunks of sentence N all emit before
  any chunk of N+1) — playback correctness is never traded for speed.
- ``feed()`` never blocks on synthesis, so the agent event loop keeps streaming.
- A synthesis failure for one sentence is contained (logged by the caller's synth
  wrapper); the pipeline continues with the next sentence.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger("app.agent.tts_pipeline")

SynthFn = Callable[[str], AsyncIterator[bytes]]
EmitFn = Callable[[int, str, bytes], Awaitable[None]]
"""EmitFn(sentence_index, sentence_text, chunk) — called in order, chunk-streamed."""


class SpeechPipeline:
    """One per turn. ``feed(text)`` returns immediately; ``drain()`` awaits the tail."""

    def __init__(self, synth: SynthFn, emit: EmitFn, *, lookahead: int = 2) -> None:
        self._synth = synth
        self._emit = emit
        self._sem = asyncio.Semaphore(lookahead)
        self._queue: asyncio.Queue[tuple[int, str, asyncio.Task] | None] = asyncio.Queue()
        self._emitter = asyncio.create_task(self._emit_loop())
        self._index = 0
        self._failed = False

    def feed(self, text: str) -> None:
        """Enqueue a sentence; synthesis starts as soon as a lookahead slot frees."""
        idx = self._index
        self._index += 1
        task = asyncio.create_task(self._synth_one(text))
        self._queue.put_nowait((idx, text, task))

    async def _synth_one(self, text: str) -> list[bytes]:
        async with self._sem:
            chunks: list[bytes] = []
            async for chunk in self._synth(text):
                chunks.append(chunk)
            return chunks

    async def _emit_loop(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            idx, text, task = item
            try:
                chunks = await task
            except Exception:
                logger.exception("pipeline_synth_failed sentence_index=%d", idx)
                self._failed = True
                continue
            for chunk in chunks:
                await self._emit(idx, text, chunk)

    async def drain(self) -> bool:
        """Finish the turn: await all queued synthesis + emission. True if all OK."""
        self._queue.put_nowait(None)
        await self._emitter
        return not self._failed
