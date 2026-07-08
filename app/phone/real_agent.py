"""Real-agent adapter for the phone channel (COORDINATION §5 step 5 integration).

Replaces :class:`app.phone.fake_agent.FakeAgent` in production: one
:class:`PhoneCallRuntime` per call implements the :class:`SessionRecorder` protocol
*and* produces the ``TurnAgent``, so the ``sessions`` row, case file, and memory are
one shared state. Turns run through ``app.agent.core.run_turn`` (the same
FunctionAgent loop the web channel uses); sentences are TTS-synthesized as
**PCM16 @ 24 kHz** (``response_format="pcm"`` — the bridge's expected ``emit_audio``
input, resampled to 8 kHz μ-law internally).

Latency-engineering (2026-07-08 RCA fixes):
- P0-2: the cached filler plays at the start of every turn (right after STT), masking
  the LLM head instead of waiting for the first ``ToolInvoked``.
- P0-3: per-sentence synthesis runs through ``SpeechPipeline`` (lookahead 2) — the
  measured 75% serialized-TTS root cause.
- O4: persistence + recording writes are fire-and-forget off the turn path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime

from app.agent import tts_cache
from app.agent.core import SentenceReady, run_turn
from app.agent.fillers import PHONE_TOOL_FILLER as TOOL_FILLER
from app.agent.fillers import PHONE_TURN_FAILED_FALLBACK as TURN_FAILED_FALLBACK
from app.agent.prompts import GREETING
from app.agent.session_store import SessionState, load_or_create_session, persist_session
from app.agent.tts_pipeline import SpeechPipeline
from app.contracts import SessionBridge
from app.db.base import get_sessionmaker
from app.db.models_core import SessionRecord
from app.phone.call_context import PhoneCallContext
from app.phone.stt import pcm16_to_wav_bytes

logger = logging.getLogger("app.phone")

# specs/features/2026-07-08-call-recording-replay: agent-turn wav, written
# best-effort at TTS time (mirrors the web channel's hook).
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")


def _synth(text: str):
    return tts_cache.synthesize_cached(text, response_format="pcm")


class PhoneCallRuntime:
    """Per-call state: SessionRecorder + TurnAgent bound to one SessionState."""

    def __init__(self) -> None:
        self._state: SessionState | None = None
        self._context: PhoneCallContext | None = None

    # ------------------------------------------------------------------ recorder
    async def start_session(self, context: PhoneCallContext) -> str:
        factory = get_sessionmaker()
        async with factory() as db:
            state = await load_or_create_session(db, None)
            record = await db.get(SessionRecord, state.session_id)
            if record is not None:
                record.channel = "phone"
                if context.call_sid:
                    record.call_sid = context.call_sid
                await db.commit()
        if context.caller_number:
            # No phone field in the frozen CaseFile.customer contract; logged only.
            logger.info(
                "phone_session_started session=%s caller=%s",
                state.session_id,
                context.caller_number,
            )
        self._state = state
        self._context = context
        context.session_id = str(state.session_id)
        context.channel = "phone"
        return str(state.session_id)

    async def end_session(self, session_id: str) -> None:
        factory = get_sessionmaker()
        async with factory() as db:
            record = await db.get(SessionRecord, uuid.UUID(session_id))
            if record is not None:
                record.ended_at = datetime.now(UTC)
                await db.commit()
            if self._state is not None:
                await persist_session(db, self._state)

    # ------------------------------------------------------------------ agent
    def agent(self) -> RealAgent:
        return RealAgent(self)

    async def _ensure_state(self) -> SessionState:
        if self._state is None:
            # start event never arrived — degrade gracefully to an unpersisted
            # in-call state rather than dropping the call.
            factory = get_sessionmaker()
            async with factory() as db:
                self._state = await load_or_create_session(db, None)
        return self._state


class RealAgent:
    """``TurnAgent`` adapter around ``run_turn`` + the parallel TTS pipeline."""

    def __init__(self, runtime: PhoneCallRuntime) -> None:
        self._runtime = runtime

    async def greet(self, bridge: SessionBridge) -> None:
        state = await self._runtime._ensure_state()
        await self._say(bridge, GREETING, state)
        self._persist_async(state)

    async def handle_turn(
        self, text: str, bridge: SessionBridge, *, audio_seq: int | None = None
    ) -> None:
        state = await self._runtime._ensure_state()
        entry: dict[str, object] = {
            "role": "user",
            "text": text,
            "ts": datetime.now(UTC).isoformat(),
        }
        if audio_seq is not None:
            entry["audio_seq"] = audio_seq
        state.transcript.append(entry)

        # P0-2: cached filler immediately — masks LLM TTFT + tool round trips.
        await self._say(bridge, TOOL_FILLER, state, record_transcript=False)

        # P0-3: sentences through the parallel pipeline; ordered chunks to the bridge.
        sentence_audio: list[tuple[dict, bytearray]] = []

        async def emit(idx: int, sentence: str, chunk: bytes) -> None:
            if idx < len(sentence_audio):
                sentence_audio[idx][1].extend(chunk)
            await bridge.emit_audio(chunk)

        pipeline = SpeechPipeline(_synth, emit, lookahead=2)
        spoke = False
        try:
            async for event in run_turn(
                state.case_file, state.memory, text, session_id=state.session_id
            ):
                if isinstance(event, SentenceReady):
                    spoke = True
                    await bridge.emit_transcript("agent", event.text)
                    s_entry: dict[str, object] = {
                        "role": "agent",
                        "text": event.text,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                    state.transcript.append(s_entry)
                    sentence_audio.append((s_entry, bytearray()))
                    pipeline.feed(event.text)
            await pipeline.drain()
        except Exception:
            logger.exception("phone_turn_failed session=%s", state.session_id)
            await pipeline.drain()
            if not spoke:
                await self._say(bridge, TURN_FAILED_FALLBACK, state)
        for s_entry, audio in sentence_audio:
            self._record_async(state, s_entry, bytes(audio))
        self._persist_async(state)

    async def _say(
        self,
        bridge: SessionBridge,
        sentence: str,
        state: SessionState,
        *,
        record_transcript: bool = True,
    ) -> None:
        """Serial single-line path (greeting/filler/fallback — cached strings)."""
        await bridge.emit_transcript("agent", sentence)
        entry: dict[str, object] = {
            "role": "agent",
            "text": sentence,
            "ts": datetime.now(UTC).isoformat(),
        }
        if record_transcript:
            state.transcript.append(entry)
        pcm_bytes = bytearray()
        try:
            async for chunk in _synth(sentence):
                pcm_bytes.extend(chunk)
                await bridge.emit_audio(chunk)
        except Exception:
            logger.exception("phone_tts_failed session=%s", state.session_id)
        else:
            if record_transcript:
                self._record_async(state, entry, bytes(pcm_bytes))

    # ------------------------------------------------------------- O4 async IO
    def _record_async(self, state: SessionState, entry: dict, audio: bytes) -> None:
        context = self._runtime._context
        if not audio or context is None:
            return
        seq = next(context.audio_seq)
        entry["audio_seq"] = seq

        def _write() -> None:
            session_dir = os.path.join(RECORDINGS_DIR, str(state.session_id))
            os.makedirs(session_dir, exist_ok=True)
            with open(os.path.join(session_dir, f"{seq:05d}.wav"), "wb") as fh:
                fh.write(pcm16_to_wav_bytes(audio, 24000))

        async def _bg() -> None:
            try:
                await asyncio.to_thread(_write)
            except Exception:
                logger.exception("recording_write_failed session=%s", state.session_id)

        asyncio.get_running_loop().create_task(_bg())

    def _persist_async(self, state: SessionState) -> None:
        async def _bg() -> None:
            try:
                factory = get_sessionmaker()
                async with factory() as db:
                    await persist_session(db, state)
            except Exception:
                logger.exception("phone_persist_failed session=%s", state.session_id)

        asyncio.get_running_loop().create_task(_bg())
