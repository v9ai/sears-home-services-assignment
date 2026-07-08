"""Real-agent adapter for the phone channel (COORDINATION §5 step 5 integration).

Replaces :class:`app.phone.fake_agent.FakeAgent` in production: one
:class:`PhoneCallRuntime` per call implements the :class:`SessionRecorder` protocol
*and* produces the ``TurnAgent``, so the ``sessions`` row, case file, and memory are
one shared state. Turns run through ``app.agent.core.run_turn`` (the same
FunctionAgent loop the web channel uses); each finished sentence is TTS-synthesized as
**PCM16 @ 24 kHz** (``response_format="pcm"`` — the bridge's expected ``emit_audio``
input, resampled to 8 kHz μ-law internally) and persisted per turn like
``app/ws/routes.py`` does.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from app.agent import tts
from app.agent.core import SentenceReady, ToolInvoked, run_turn
from app.agent.fillers import PHONE_TOOL_FILLER as TOOL_FILLER
from app.agent.fillers import PHONE_TURN_FAILED_FALLBACK as TURN_FAILED_FALLBACK
from app.agent.prompts import GREETING
from app.agent.session_store import SessionState, load_or_create_session, persist_session
from app.agent.trace import TurnTrace, log_turn_trace
from app.contracts import SessionBridge
from app.db.base import get_sessionmaker
from app.db.models_core import SessionRecord
from app.phone.call_context import PhoneCallContext
from app.phone.stt import pcm16_to_wav_bytes

logger = logging.getLogger("app.phone")

# specs/features/2026-07-08-call-recording-replay: agent-turn wav, written
# best-effort at TTS time (mirrors app/ws/routes.py's mp3-at-TTS-time hook).
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")


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
                await db.commit()
        if context.caller_number:
            # No phone field in the frozen CaseFile.customer contract; keep the caller
            # number in the case file's name slot only if nothing better arrives later.
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
            # start event never arrived (or recorder wasn't this runtime) — degrade
            # gracefully to an unpersisted in-call state rather than dropping the call.
            factory = get_sessionmaker()
            async with factory() as db:
                self._state = await load_or_create_session(db, None)
        return self._state


class RealAgent:
    """``TurnAgent`` adapter around ``run_turn`` + streamed OpenAI TTS (pcm/24 kHz)."""

    def __init__(self, runtime: PhoneCallRuntime) -> None:
        self._runtime = runtime

    async def greet(self, bridge: SessionBridge) -> None:
        state = await self._runtime._ensure_state()
        await self._say(bridge, GREETING, state)
        await self._persist(state)

    async def handle_turn(
        self,
        text: str,
        bridge: SessionBridge,
        *,
        audio_seq: int | None = None,
        trace: TurnTrace | None = None,
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
        filler_spoken = False
        try:
            async for event in run_turn(
                state.case_file, state.memory, text, session_id=state.session_id, trace=trace
            ):
                if isinstance(event, ToolInvoked) and not filler_spoken:
                    filler_spoken = True
                    await self._say(bridge, TOOL_FILLER, state)
                elif isinstance(event, SentenceReady):
                    await self._say(bridge, event.text, state)
        except Exception:
            logger.exception("phone_turn_failed session=%s", state.session_id)
            await self._say(bridge, TURN_FAILED_FALLBACK, state)
        await self._persist(state)
        if trace is not None:
            trace.mark("turn_done")
            log_turn_trace(trace, logger)

    async def _say(self, bridge: SessionBridge, sentence: str, state: SessionState) -> None:
        await bridge.emit_transcript("agent", sentence)
        state.transcript.append(
            {"role": "agent", "text": sentence, "ts": datetime.now(UTC).isoformat()}
        )
        pcm_bytes = bytearray()
        try:
            async for chunk in tts.synthesize(sentence, response_format="pcm"):
                pcm_bytes.extend(chunk)
                await bridge.emit_audio(chunk)
        except Exception:
            # Caller still gets nothing audible for this sentence, but the call
            # survives and the transcript row is recorded (mirrors app/ws/routes.py).
            logger.exception("phone_tts_failed session=%s", state.session_id)
        else:
            context = self._runtime._context
            if pcm_bytes and context is not None:
                seq = next(context.audio_seq)
                try:
                    session_dir = os.path.join(RECORDINGS_DIR, str(state.session_id))
                    os.makedirs(session_dir, exist_ok=True)
                    wav_bytes = pcm16_to_wav_bytes(bytes(pcm_bytes), 24000)
                    with open(os.path.join(session_dir, f"{seq:05d}.wav"), "wb") as fh:
                        fh.write(wav_bytes)
                    state.transcript[-1]["audio_seq"] = seq
                except Exception:
                    logger.exception("recording_write_failed session=%s", state.session_id)

    async def _persist(self, state: SessionState) -> None:
        factory = get_sessionmaker()
        try:
            async with factory() as db:
                await persist_session(db, state)
        except Exception:
            logger.exception("phone_persist_failed session=%s", state.session_id)
