"""`/ws/call` — the web session bridge (tech-stack.md → Runtime).

Frame protocol (frozen, app/contracts.py):
    client -> server: UserTextFrame ({"type": "user_text", "text": str})
    server -> client: TranscriptFrame | AudioFrame | StateFrame

The safety interrupt (mission non-negotiable 1) runs here, on the raw utterance,
*before* the agent ever sees it — see `app/agent/safety.py` for why that's structural
rather than prompt-hope.

Latency-engineering (2026-07-08 RCA fixes):
- P0-2: the cached filler plays immediately on user_text receipt — masking the whole
  STT-less web head (LLM TTFT + tool round trips).
- P0-3: per-sentence TTS runs through `SpeechPipeline` (lookahead 2) — synthesis of
  sentence N+1 overlaps N's emission, and the `run_turn` event loop is never blocked
  on synthesis (the measured 75% root cause).
- O9: audio frames carry raw PCM16 @ 24 kHz (`format="pcm24k"`) for gapless WebAudio
  playback (measured 270 ms/sentence mp3 encoding tax removed).
- O4: session persistence and recording writes are fire-and-forget off the turn path.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import logging
import os
import time
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.agent.core import SentenceReady, TurnComplete, run_turn
from app.agent.fillers import WEB_TOOL_FILLER as TOOL_CALL_FILLER
from app.agent.fillers import WEB_TURN_FAILED_FALLBACK as TURN_FAILED_FALLBACK
from app.agent.fillers import should_fire_filler
from app.agent.prompts import GREETING
from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
from app.agent.session_store import SessionState, load_or_create_session, persist_session
from app.agent.trace import TurnTrace, log_turn_trace
from app.agent.tts_cache import synthesize_cached
from app.agent.tts_pipeline import SpeechPipeline
from app.contracts import AudioFrame, StateFrame, TranscriptFrame, UserTextFrame
from app.db.base import get_sessionmaker
from app.obs import bind_call_context
from app.phone.stt import pcm16_to_wav_bytes

logger = logging.getLogger("app.ws")

router = APIRouter()

# specs/features/2026-07-08-call-recording-replay: one audio file per spoken line,
# written best-effort alongside the existing WS/TTS streaming path.
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")

AUDIO_FORMAT = "pcm24k"  # O9: raw PCM16 @ 24 kHz — see AudioFrame contract note.


def _synth(text: str):
    return synthesize_cached(text, response_format="pcm")


def _write_recording(session_id, seq: int, audio: bytes) -> None:
    session_dir = os.path.join(RECORDINGS_DIR, str(session_id))
    os.makedirs(session_dir, exist_ok=True)
    # wav-wrapped so the recordings replay endpoint serves browser-playable audio.
    with open(os.path.join(session_dir, f"{seq:05d}.wav"), "wb") as fh:
        fh.write(pcm16_to_wav_bytes(audio, 24000))


def _record_async(
    state: SessionState, entry: dict, audio_seq_counter: itertools.count, audio: bytes
) -> None:
    """O4: recording write off the turn path (thread), best-effort."""
    if not audio:
        return
    seq = next(audio_seq_counter)
    entry["audio_seq"] = seq

    async def _bg() -> None:
        try:
            await asyncio.to_thread(_write_recording, state.session_id, seq, audio)
        except Exception:
            logger.exception("recording_write_failed session=%s", state.session_id)

    asyncio.get_running_loop().create_task(_bg())


def _persist_async(state: SessionState) -> None:
    """O4: persistence off the turn path, best-effort (grounded: ~250–400 ms inline)."""

    async def _bg() -> None:
        try:
            session_factory = get_sessionmaker()
            async with session_factory() as db:
                await persist_session(db, state)
        except Exception:
            logger.exception("persist_failed session=%s", state.session_id)

    asyncio.get_running_loop().create_task(_bg())


async def _persist(state: SessionState) -> None:
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        await persist_session(db, state)


async def _speak(
    websocket: WebSocket,
    text: str,
    state: SessionState,
    seq_counter: itertools.count,
    audio_seq_counter: itertools.count,
    *,
    record_transcript: bool = True,
    turn_started_at: float | None = None,
) -> None:
    """Emit one agent line serially: transcript frame, then its streamed audio frames.

    Kept for the single-line paths (greeting, safety, filler, fallback); multi-sentence
    agent turns go through the `SpeechPipeline` in `_handle_user_text` instead.
    """
    await websocket.send_json(TranscriptFrame(role="agent", text=text).model_dump())
    entry: dict = {"role": "agent", "text": text, "ts": datetime.now(UTC).isoformat()}
    if record_transcript:
        state.transcript.append(entry)
    first_chunk = True
    audio_bytes = bytearray()
    try:
        async for chunk in _synth(text):
            if first_chunk and turn_started_at is not None:
                first_chunk = False
                logger.info(
                    "first_audio_latency_ms=%.0f session=%s",
                    (time.monotonic() - turn_started_at) * 1000,
                    state.session_id,
                )
            audio_bytes.extend(chunk)
            frame = AudioFrame(
                chunk=base64.b64encode(chunk).decode("ascii"),
                seq=next(seq_counter),
                format=AUDIO_FORMAT,
            )
            await websocket.send_json(frame.model_dump())
    except WebSocketDisconnect:
        raise
    except Exception:
        # TTS is a nice-to-have on top of the transcript, which has already been sent.
        logger.exception("tts_failed session=%s", state.session_id)
    else:
        if record_transcript:
            _record_async(state, entry, audio_seq_counter, bytes(audio_bytes))


async def _send_state(websocket: WebSocket, state: SessionState) -> None:
    await websocket.send_json(StateFrame(case_file=state.case_file).model_dump())


async def _handle_user_text(
    websocket: WebSocket,
    state: SessionState,
    text: str,
    seq_counter: itertools.count,
    audio_seq_counter: itertools.count,
    turn_index: int = 0,
) -> None:
    turn_started_at = time.monotonic()
    bind_call_context(session_id=str(state.session_id), turn_index=turn_index)
    trace = TurnTrace(channel="web", session_id=state.session_id, turn_index=turn_index)
    trace.mark("t0", ts=turn_started_at)
    try:
        await websocket.send_json(TranscriptFrame(role="user", text=text).model_dump())
        state.transcript.append({"role": "user", "text": text, "ts": datetime.now(UTC).isoformat()})

        safety_category = detect_safety_trigger(text)
        if safety_category is not None:
            logger.info(
                "safety_interrupt category=%s session=%s", safety_category, state.session_id
            )
            state.case_file.safety_flag = True
            await _speak(
                websocket,
                SAFETY_RESPONSE,
                state,
                seq_counter,
                audio_seq_counter,
                turn_started_at=turn_started_at,
            )
            await _send_state(websocket, state)
            _persist_async(state)
            return

        # P0-2: cached filler the moment the turn starts — masks LLM TTFT + tools.
        # Launched CONCURRENTLY with the agent turn: awaiting it inline would delay
        # run_turn's start by the synth time (measured — the filler must never cost
        # head latency, only fill it). Debounced (FILLER_DEBOUNCE_S) so rapid
        # consecutive turns can't stack overlapping fillers; stamp the fire time only
        # when we actually launch one, so at most one plays per debounce window.
        filler_task: asyncio.Task[None] | None = None
        if should_fire_filler(state.last_filler_at, turn_started_at):
            state.last_filler_at = turn_started_at
            filler_task = asyncio.create_task(
                _speak(
                    websocket,
                    TOOL_CALL_FILLER,
                    state,
                    seq_counter,
                    audio_seq_counter,
                    record_transcript=False,
                    turn_started_at=turn_started_at,
                )
            )

        # P0-3: multi-sentence turn through the parallel pipeline. Transcript frames
        # go out the moment each sentence is ready; audio chunks stream in order.
        first_audio_logged = False

        async def emit(idx: int, sentence: str, chunk: bytes) -> None:
            nonlocal first_audio_logged
            if not first_audio_logged:
                first_audio_logged = True
                trace.mark("first_audio")
                logger.info(
                    "first_sentence_audio_latency_ms=%.0f session=%s",
                    (time.monotonic() - turn_started_at) * 1000,
                    state.session_id,
                )
            if idx < len(sentence_entries):
                sentence_entries[idx][1].extend(chunk)
            frame = AudioFrame(
                chunk=base64.b64encode(chunk).decode("ascii"),
                seq=next(seq_counter),
                format=AUDIO_FORMAT,
            )
            await websocket.send_json(frame.model_dump())

        pipeline = SpeechPipeline(_synth, emit, lookahead=2)
        sentence_entries: list[tuple[dict, bytearray]] = []
        text_started = False
        try:
            async for event in run_turn(
                state.case_file, state.memory, text, session_id=state.session_id, trace=trace
            ):
                if isinstance(event, SentenceReady):
                    text_started = True
                    await websocket.send_json(
                        TranscriptFrame(role="agent", text=event.text).model_dump()
                    )
                    entry = {
                        "role": "agent",
                        "text": event.text,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                    state.transcript.append(entry)
                    sentence_entries.append((entry, bytearray()))
                    pipeline.feed(event.text)
                elif isinstance(event, TurnComplete):
                    logger.info(
                        "turn_complete session=%s chars=%d",
                        state.session_id,
                        len(event.full_text),
                    )
            if filler_task is not None:
                await filler_task
            await pipeline.drain()
            for entry, audio in sentence_entries:
                _record_async(state, entry, audio_seq_counter, bytes(audio))
            log_turn_trace(trace, logger)
        except WebSocketDisconnect:
            if filler_task is not None:
                filler_task.cancel()
            raise
        except Exception:
            logger.exception("agent_turn_failed session=%s", state.session_id)
            if filler_task is not None:
                await filler_task
            await pipeline.drain()
            if not text_started:
                await _speak(websocket, TURN_FAILED_FALLBACK, state, seq_counter, audio_seq_counter)
            log_turn_trace(trace, logger)

        await _send_state(websocket, state)
        _persist_async(state)
    except WebSocketDisconnect:
        logger.info("client disconnected mid-turn session=%s", state.session_id)
        await _persist(state)
        raise


@router.websocket("/ws/call")
async def ws_call(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session_id")
    await websocket.accept()

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        state = await load_or_create_session(db, session_id)

    seq_counter = itertools.count(start=1)
    audio_seq_counter = itertools.count(start=1)
    turn_counter = itertools.count(start=1)
    bind_call_context(session_id=str(state.session_id))
    await _send_state(websocket, state)
    for line in state.transcript:
        frame = TranscriptFrame(role=line["role"], text=line["text"])
        await websocket.send_json(frame.model_dump())

    if state.is_new:
        await _speak(websocket, GREETING, state, seq_counter, audio_seq_counter)
        _persist_async(state)

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = UserTextFrame.model_validate(raw)
            except ValidationError:
                logger.warning("ignoring malformed frame session=%s raw=%r", state.session_id, raw)
                continue
            await _handle_user_text(
                websocket,
                state,
                frame.text,
                seq_counter,
                audio_seq_counter,
                turn_index=next(turn_counter),
            )
    except WebSocketDisconnect:
        logger.info("client disconnected session=%s", state.session_id)
