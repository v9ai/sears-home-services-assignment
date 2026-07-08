"""`/ws/call` — the web session bridge (tech-stack.md → Runtime).

Frame protocol (frozen, app/contracts.py):
    client -> server: UserTextFrame ({"type": "user_text", "text": str})
    server -> client: TranscriptFrame | AudioFrame | StateFrame

The safety interrupt (mission non-negotiable 1) runs here, on the raw utterance,
*before* the agent ever sees it — see `app/agent/safety.py` for why that's structural
rather than prompt-hope.
"""

from __future__ import annotations

import base64
import itertools
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.agent.core import SentenceReady, ToolInvoked, TurnComplete, run_turn
from app.agent.prompts import GREETING
from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
from app.agent.session_store import SessionState, load_or_create_session, persist_session
from app.agent.tts import synthesize
from app.contracts import AudioFrame, StateFrame, TranscriptFrame, UserTextFrame
from app.db.base import get_sessionmaker

logger = logging.getLogger("app.ws")

router = APIRouter()

TOOL_CALL_FILLER = "Let me check that for you..."
TURN_FAILED_FALLBACK = (
    "Sorry, I hit a snag on my end. Could you say that again, or rephrase it for me?"
)


async def _speak(
    websocket: WebSocket,
    text: str,
    state: SessionState,
    seq_counter: itertools.count,
    *,
    record_transcript: bool = True,
    turn_started_at: float | None = None,
) -> None:
    """Emit one agent line: a transcript frame, then its streamed TTS audio frames.

    ``turn_started_at`` is only passed for the first spoken line of a turn, so the
    first-audio latency (requirements.md Decision 2 budget) is logged exactly once.
    """
    await websocket.send_json(TranscriptFrame(role="agent", text=text).model_dump())
    if record_transcript:
        state.transcript.append({"role": "agent", "text": text})
    first_chunk = True
    try:
        async for chunk in synthesize(text):
            if first_chunk and turn_started_at is not None:
                first_chunk = False
                logger.info(
                    "first_audio_latency_ms=%.0f session=%s",
                    (time.monotonic() - turn_started_at) * 1000,
                    state.session_id,
                )
            frame = AudioFrame(chunk=base64.b64encode(chunk).decode("ascii"), seq=next(seq_counter))
            await websocket.send_json(frame.model_dump())
    except WebSocketDisconnect:
        # The caller hung up mid-line — that's a disconnect, not a TTS failure. Let it
        # propagate so the turn unwinds cleanly instead of being mislabeled below and
        # having the loop keep trying to push audio at a closed socket.
        raise
    except Exception:
        # TTS is a nice-to-have on top of the transcript, which has already been sent
        # above — a synthesis hiccup (bad key, rate limit, network blip) shouldn't take
        # the whole session down. The caller still sees the text; they just lose audio
        # for this one line.
        logger.exception("tts_failed session=%s", state.session_id)


async def _send_state(websocket: WebSocket, state: SessionState) -> None:
    await websocket.send_json(StateFrame(case_file=state.case_file).model_dump())


async def _persist(state: SessionState) -> None:
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        await persist_session(db, state)


async def _handle_user_text(
    websocket: WebSocket, state: SessionState, text: str, seq_counter: itertools.count
) -> None:
    turn_started_at = time.monotonic()
    try:
        await websocket.send_json(TranscriptFrame(role="user", text=text).model_dump())
        state.transcript.append({"role": "user", "text": text})

        safety_category = detect_safety_trigger(text)
        if safety_category is not None:
            logger.info(
                "safety_interrupt category=%s session=%s", safety_category, state.session_id
            )
            state.case_file.safety_flag = True
            await _speak(
                websocket, SAFETY_RESPONSE, state, seq_counter, turn_started_at=turn_started_at
            )
            await _send_state(websocket, state)
            await _persist(state)
            return

        text_started = False
        filler_sent = False
        try:
            async for event in run_turn(
                state.case_file, state.memory, text, session_id=state.session_id
            ):
                if isinstance(event, ToolInvoked):
                    if not text_started and not filler_sent:
                        filler_sent = True
                        await _speak(
                            websocket,
                            TOOL_CALL_FILLER,
                            state,
                            seq_counter,
                            record_transcript=False,
                            turn_started_at=turn_started_at,
                        )
                elif isinstance(event, SentenceReady):
                    first_sentence = not text_started
                    text_started = True
                    await _speak(
                        websocket,
                        event.text,
                        state,
                        seq_counter,
                        turn_started_at=(
                            turn_started_at if (first_sentence and not filler_sent) else None
                        ),
                    )
                elif isinstance(event, TurnComplete):
                    logger.info(
                        "turn_complete session=%s chars=%d",
                        state.session_id,
                        len(event.full_text),
                    )
        except WebSocketDisconnect:
            # Caller hung up mid-turn — not an agent failure. Re-raise to the outer
            # handler below so we stop sending instead of degrading to a fallback line.
            raise
        except Exception:
            # The LLM/tool-calling round trip failed (network blip, rate limit, bad
            # response) — degrade to a spoken apology rather than dropping the
            # connection, so the caller isn't left hanging mid-call.
            logger.exception("agent_turn_failed session=%s", state.session_id)
            if not text_started:
                await _speak(websocket, TURN_FAILED_FALLBACK, state, seq_counter)

        await _send_state(websocket, state)
        await _persist(state)
    except WebSocketDisconnect:
        # Caller hung up mid-turn (routine on the voice channel). Persist whatever the
        # turn captured so a reconnect rehydrates it, then re-raise for ws_call to log
        # the disconnect. Attempting any further send on the now-closed socket is what
        # produced the "Cannot call send once a close message has been sent" noise.
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
    await _send_state(websocket, state)
    for line in state.transcript:
        frame = TranscriptFrame(role=line["role"], text=line["text"])
        await websocket.send_json(frame.model_dump())

    if state.is_new:
        await _speak(websocket, GREETING, state, seq_counter)
        await _persist(state)

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = UserTextFrame.model_validate(raw)
            except ValidationError:
                logger.warning("ignoring malformed frame session=%s raw=%r", state.session_id, raw)
                continue
            await _handle_user_text(websocket, state, frame.text, seq_counter)
    except WebSocketDisconnect:
        logger.info("client disconnected session=%s", state.session_id)
