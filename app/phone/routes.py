"""``/ws/twilio`` -- the Media Streams WebSocket endpoint.

Wires together the pieces owned by this feature: mu-law codec (:mod:`app.phone.codec`),
VAD turn segmentation (:mod:`app.phone.vad`), STT (:mod:`app.phone.stt`), the session
bridge (:mod:`app.phone.bridge`), and call metadata capture (:mod:`app.phone.call_context`).

Message loop per Twilio's Media Streams protocol (requirements.md "Contract shapes"):
``start`` (stream/call metadata) -> many ``media`` frames -> ``stop``. Barge-in: while
the bridge is mid-playback, any inbound frame that clears the VAD speech threshold
interrupts it immediately (send ``clear``, drop queued audio) before segmentation even
finishes a full turn -- responsiveness matters more than a clean cutoff there.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import time

from app.agent.trace import TurnTrace, log_turn_trace
from app.obs import bind_call_context, log_event
from app.phone.bridge import TurnAgent, TwilioMediaBridge
from app.phone.call_context import (
    InMemorySessionRecorder,
    PhoneCallContext,
    SessionRecorder,
)
from app.phone.codec import decode_b64_frame, mulaw_to_pcm16
from app.phone.fake_agent import FakeAgent
from app.phone.stt import Transcriber, get_transcriber, pcm16_to_wav_bytes
from app.phone.vad import TurnSegmenter, frame_is_speech

logger = logging.getLogger("app.phone")

router = APIRouter()

AgentFactory = Callable[[], TurnAgent]

# specs/features/2026-07-08-call-recording-replay: caller-turn wav, written
# best-effort at STT time (mirrors app/ws/routes.py's mp3-at-TTS-time hook).
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")


def _default_agent_factory() -> TurnAgent:
    # Stub seam (COORDINATION.md §4): the real agent swap-in is an integration step,
    # not this feature's -- see fake_agent.py's module docstring.
    return FakeAgent()


async def handle_twilio_media_stream(
    websocket: WebSocket,
    *,
    agent_factory: AgentFactory = _default_agent_factory,
    transcriber: Transcriber | None = None,
    session_recorder: SessionRecorder | None = None,
) -> TwilioMediaBridge:
    """Runs the full connection lifecycle; returns the bridge for post-hoc inspection
    (tests use this to assert on ``bridge.transcript`` / ``bridge.latency``)."""
    client = getattr(websocket, "client", None)
    logger.info("phone_ws_connecting client=%s", client)
    try:
        await websocket.accept()

        transcriber = transcriber or get_transcriber()
        session_recorder = session_recorder or InMemorySessionRecorder()

        agent = agent_factory()
        bridge = TwilioMediaBridge(websocket, agent)
        segmenter = TurnSegmenter()
        context = PhoneCallContext()
    except Exception:
        # Setup (accept/agent construction) is before the message loop even starts --
        # an "an application error has occurred" from Twilio with ZERO context in the
        # logs otherwise. Log everything we have and let it propagate (there's no call
        # to degrade yet).
        logger.exception("phone_ws_setup_failed client=%s", client)
        raise

    logger.info("phone_ws_accepted client=%s", client)

    # 2026-07-09-observability-tracing: per-call counters for twilio.call.summary.
    call_started = time.monotonic()
    counters = {"frames_in": 0, "turns": 0, "barge_ins": 0}

    def _log_call_summary() -> None:
        samples = bridge.latency.samples
        log_event(
            logger,
            "twilio.call.summary",
            turns=counters["turns"],
            frames_in=counters["frames_in"],
            barge_ins=counters["barge_ins"],
            duration_s=time.monotonic() - call_started,
            eos_first_audio_p50_ms=bridge.latency.p50 * 1000 if samples else None,
            eos_first_audio_p95_ms=bridge.latency.p95 * 1000 if samples else None,
        )

    async def _close_out_turn(pcm16: bytes | None) -> None:
        if not pcm16:
            return
        counters["turns"] += 1
        turn_index = counters["turns"]
        bind_call_context(turn_index=turn_index)
        logger.info(
            "phone_turn_stt_started call=%s session=%s frame_bytes=%d",
            context.call_sid,
            context.session_id,
            len(pcm16),
        )
        log_event(logger, "twilio.turn.closed", speech_ms=len(pcm16) / 16)
        trace = TurnTrace(channel="phone", session_id=context.session_id, turn_index=turn_index)
        bridge.mark_end_of_speech(trace)
        stt_started = time.monotonic()
        text = await transcriber.transcribe(pcm16, 8000)
        trace.mark("stt_done")
        log_event(
            logger,
            "twilio.stt",
            ms=(time.monotonic() - stt_started) * 1000,
            chars=len(text or ""),
        )
        logger.info(
            "phone_turn_stt_done call=%s session=%s text=%r",
            context.call_sid,
            context.session_id,
            text,
        )
        if text:
            audio_seq: int | None = None
            if context.session_id:
                audio_seq = next(context.audio_seq)

                def _write(seq: int = audio_seq, pcm: bytes = pcm16) -> None:
                    session_dir = os.path.join(RECORDINGS_DIR, context.session_id)
                    os.makedirs(session_dir, exist_ok=True)
                    with open(os.path.join(session_dir, f"{seq:05d}.wav"), "wb") as fh:
                        fh.write(pcm16_to_wav_bytes(pcm, 8000))

                try:
                    await asyncio.to_thread(_write)
                except Exception:
                    logger.exception(
                        "recording_write_failed call=%s session=%s seq=%s",
                        context.call_sid,
                        context.session_id,
                        audio_seq,
                    )
            turn_started = time.monotonic()
            await bridge.receive_user_utterance(text, audio_seq=audio_seq)
            log_event(
                logger,
                "twilio.turn.processed",
                ms=(time.monotonic() - turn_started) * 1000,
                ok=True,
            )
            log_turn_trace(trace, logger)

    async def _safe_close_out_turn(pcm16: bytes | None) -> None:
        # Premature call-end RCA F3: a per-turn failure (STT hiccup, provider blip,
        # dead socket mid-reply) must degrade THAT TURN, never unwind the whole WS
        # handler — an exception escaping the message loop closes the stream, and
        # with <Connect><Stream> a closed stream ENDS THE CALL.
        try:
            await _close_out_turn(pcm16)
        except Exception:
            logger.exception(
                "phone_turn_processing_failed call=%s session=%s frame_bytes=%s",
                context.call_sid,
                context.session_id,
                len(pcm16) if pcm16 else 0,
            )
            log_event(logger, "twilio.turn.processed", ok=False)

    def _submit_turn(pcm16: bytes | None, prev: asyncio.Task | None) -> asyncio.Task | None:
        # Premature call-end RCA F2: turn processing runs as a task so the message
        # loop KEEPS READING (VAD + barge-in stay live during agent turns; Twilio
        # frames never back up). Turns are chained, not dropped, if the caller
        # finishes another utterance while one is still processing.
        if not pcm16:
            return prev
        if prev is not None and not prev.done():

            async def _chained() -> None:
                await prev
                await _safe_close_out_turn(pcm16)

            return asyncio.create_task(_chained())
        return asyncio.create_task(_safe_close_out_turn(pcm16))

    turn_task: asyncio.Task | None = None
    media_frame_count = 0
    try:
        while True:
            message = await websocket.receive_json()
            event = message.get("event")
            logger.debug(
                "phone_ws_event call=%s event=%s", context.call_sid, event
            )

            if event == "start":
                start = message.get("start", {})
                context.call_sid = start.get("callSid")
                context.stream_sid = start.get("streamSid") or message.get("streamSid")
                custom_params = start.get("customParameters", {}) or {}
                context.caller_number = custom_params.get("From")
                context.called_number = custom_params.get("To")
                bridge.bind_stream(context.stream_sid)
                bind_call_context(call_sid=context.call_sid)
                logger.info(
                    "phone_call_started call=%s stream=%s from=%s to=%s",
                    context.call_sid,
                    context.stream_sid,
                    context.caller_number,
                    context.called_number,
                )
                try:
                    await session_recorder.start_session(context)
                except Exception:
                    # A DB blip at answer must not kill the call: the session just
                    # goes unpersisted (recordings skip on session_id None).
                    logger.exception(
                        "phone_start_session_failed call=%s stream=%s",
                        context.call_sid,
                        context.stream_sid,
                    )
                else:
                    bind_call_context(session_id=context.session_id)
                    logger.info(
                        "phone_session_bound call=%s session=%s",
                        context.call_sid,
                        context.session_id,
                    )
                # Phone etiquette: the agent speaks first. FakeAgent (tests) has no
                # greet; the real adapter plays the standard greeting on answer.
                greet = getattr(agent, "greet", None)
                if greet is not None:
                    try:
                        await greet(bridge)
                    except Exception:
                        logger.exception(
                            "phone_greet_failed call=%s session=%s",
                            context.call_sid,
                            context.session_id,
                        )
                    else:
                        logger.info(
                            "phone_greet_done call=%s session=%s",
                            context.call_sid,
                            context.session_id,
                        )
                log_event(
                    logger,
                    "twilio.stream.start",
                    call=context.call_sid,
                    stream=context.stream_sid,
                    session=context.session_id,
                )

            elif event == "media":
                media_frame_count += 1
                counters["frames_in"] += 1
                # Premature call-end RCA F1: a single malformed/undecodable frame or a
                # barge-in/VAD hiccup must drop that FRAME, never the message loop --
                # same failure class as F2/F3, just further upstream.
                try:
                    payload = message.get("media", {}).get("payload", "")
                    mulaw = decode_b64_frame(payload)
                    pcm8k = mulaw_to_pcm16(mulaw)

                    if bridge.is_playing and frame_is_speech(pcm8k):
                        counters["barge_ins"] += 1
                        logger.info(
                            "phone_barge_in call=%s session=%s frame=%d",
                            context.call_sid,
                            context.session_id,
                            media_frame_count,
                        )
                        log_event(logger, "twilio.bargein")
                        await bridge.interrupt_playback()

                    turn_task = _submit_turn(segmenter.push(pcm8k), turn_task)
                except Exception:
                    logger.exception(
                        "phone_media_frame_failed call=%s session=%s frame=%d payload_len=%d",
                        context.call_sid,
                        context.session_id,
                        media_frame_count,
                        len(message.get("media", {}).get("payload") or ""),
                    )

            elif event == "stop":
                logger.info(
                    "phone_call_stop_received call=%s session=%s frames=%d",
                    context.call_sid,
                    context.session_id,
                    media_frame_count,
                )
                if turn_task is not None:
                    await turn_task
                await _safe_close_out_turn(segmenter.flush())
                await bridge.drain()
                _log_call_summary()
                if context.session_id:
                    await session_recorder.end_session(context.session_id)
                logger.info(
                    "phone_call_ended call=%s session=%s reason=stop",
                    context.call_sid,
                    context.session_id,
                )
                break

            else:
                logger.debug(
                    "phone_ws_unknown_event call=%s event=%r keys=%s",
                    context.call_sid,
                    event,
                    list(message.keys()),
                )

    except WebSocketDisconnect as exc:
        logger.info(
            "phone_call_ended call=%s session=%s reason=disconnect code=%s frames=%d",
            context.call_sid,
            context.session_id,
            getattr(exc, "code", None),
            media_frame_count,
        )
        if turn_task is not None and not turn_task.done():
            # The socket is gone; the in-flight turn can't speak to anyone.
            turn_task.cancel()
        await bridge.drain()
        _log_call_summary()
        if context.session_id:
            await session_recorder.end_session(context.session_id)
    except Exception:
        # Anything NOT already contained above (F1/F2/F3) escaping here is exactly the
        # 31921 failure shape: our server closes the Media Streams WebSocket and Twilio
        # ends the call. There is no safe way to keep the loop alive from an unknown
        # exception at this level, so log every bit of context we have and re-raise.
        logger.exception(
            "phone_ws_loop_failed call=%s session=%s stream=%s frames=%d",
            context.call_sid,
            context.session_id,
            context.stream_sid,
            media_frame_count,
        )
        raise

    return bridge


@router.websocket("/ws/twilio")
async def twilio_media_stream(websocket: WebSocket) -> None:
    # Production wiring (COORDINATION §5 step 5): one PhoneCallRuntime per call binds
    # the real agent and the Postgres-backed session recorder to shared state.
    from app.phone.real_agent import PhoneCallRuntime

    runtime = PhoneCallRuntime()
    await handle_twilio_media_stream(
        websocket, agent_factory=runtime.agent, session_recorder=runtime
    )
