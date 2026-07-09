"""Twilio telephony channel: the ``/twilio/voice`` webhook + the ``/ws/twilio`` Media
Streams endpoint, exposed as ``phone_router`` for ``app.main`` to mount.

The media transport is now a **Pipecat** pipeline (`app/voice`): the hand-rolled µ-law
codec, RMS VAD, batch STT, and media bridge that used to live in this package were
replaced by Pipecat's Twilio serializer + FastAPI WebSocket transport + Silero VAD. Only
the webhook, TwiML, and signature validation remain here — the ``/ws/twilio`` WebSocket
handler now lives in ``app/voice/routes.py`` and calls ``app.voice.bot.run_bot``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.phone.webhook import router as _webhook_router
from app.voice.routes import router as _ws_router  # Pipecat-backed Media Streams WS

phone_router = APIRouter()
phone_router.include_router(_webhook_router)
phone_router.include_router(_ws_router)

__all__ = ["phone_router"]
