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

from fastapi import APIRouter, WebSocket

from app.obs import bind_call_context
from app.voice.bot import run_bot

logger = logging.getLogger("app.voice")

router = APIRouter()


@router.websocket("/ws/twilio")
async def twilio_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    # Twilio sends `connected` first, then `start` (which carries streamSid/callSid and the
    # <Parameter> customParameters). Read until `start` so we can build the serializer.
    stream_sid: str | None = None
    call_sid: str | None = None
    for _ in range(5):  # a small bound; `start` is the 1st or 2nd frame in practice
        message = json.loads(await websocket.receive_text())
        if message.get("event") == "start":
            start = message.get("start", {})
            stream_sid = start.get("streamSid")
            call_sid = start.get("callSid") or start.get("customParameters", {}).get("CallSid")
            break

    if not stream_sid:
        logger.warning("twilio_ws_no_start_event — closing socket")
        await websocket.close()
        return

    bind_call_context(call_sid=call_sid, session_id=None)
    logger.info("twilio_ws_start stream=%s call=%s", stream_sid, call_sid)
    await run_bot(websocket, stream_sid, call_sid)
