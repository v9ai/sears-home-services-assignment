"""`/ws/twilio` — the Twilio Media Streams WebSocket, now backed by Pipecat.

This replaces the hand-rolled `start`/`media`/`stop` loop that used to live in
`app/phone/routes.py`. Twilio opens this socket (per the TwiML `<Connect><Stream>` built
in `app/phone/twiml.py`, unchanged) and sends a `connected` then a `start` message; we
read those to learn the `streamSid`/`callSid`, then hand the socket to Pipecat's
`run_bot` (`app/voice/bot.py`), which drives transport → STT → LLM → TTS from here on.

The inbound webhook (`POST /twilio/voice`, `app/phone/webhook.py`) and its signature
validation are untouched — only the media transport changed.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.obs import bind_call_context, log_event
from app.voice.bot import run_bot

logger = logging.getLogger("app.voice")

router = APIRouter()

# `start` is the 1st or 2nd frame in practice; bound how many frames we'll read so a peer that
# never sends `start` can't stream at us forever before we have the streamSid/callSid.
_MAX_HANDSHAKE_FRAMES = 5


@router.websocket("/ws/twilio")
async def twilio_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    # Twilio sends `connected` first, then `start` (which carries streamSid/callSid and the
    # <Parameter> customParameters). Read until `start` so we can build the serializer. A
    # malformed/binary frame or abrupt disconnect during this handshake must not crash the
    # worker — one bad frame is skipped, a disconnect closes cleanly.
    stream_sid: str | None = None
    call_sid: str | None = None
    for _ in range(_MAX_HANDSHAKE_FRAMES):
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            log_event(logger, "twilio.ws.disconnected_during_handshake")
            return
        except (KeyError, RuntimeError):
            # Non-text (binary) frame, or a receive after the peer went away — skip it.
            log_event(logger, "voice.malformed_handshake_frame", reason="non_text_frame")
            continue
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log_event(logger, "voice.malformed_handshake_frame")
            continue
        if message.get("event") == "start":
            start = message.get("start", {}) or {}
            stream_sid = start.get("streamSid")
            call_sid = start.get("callSid") or start.get("customParameters", {}).get("CallSid")
            break

    if not stream_sid:
        log_event(logger, "twilio.ws.no_start_event")
        await websocket.close()
        return

    bind_call_context(call_sid=call_sid, session_id=None)
    log_event(logger, "twilio.stream.start", stream=stream_sid, call=call_sid)
    await run_bot(websocket, stream_sid, call_sid)
