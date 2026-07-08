"""Twilio telephony channel (roadmap Phase 5): webhook, TwiML, codec, VAD, media bridge.

Owned exclusively by the telephony-twilio feature (COORDINATION.md §3). Exposes
``phone_router`` -- combining the ``/twilio/voice`` webhook and the ``/ws/twilio``
Media Streams endpoint -- for ``app.main`` to mount. Not wired into ``app.main`` by
this feature itself (``app/main.py`` is a shared file outside this feature's ownership
map row); see the "Integration deltas" section of this feature's ``plan.md``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.phone.routes import router as _ws_router
from app.phone.webhook import router as _webhook_router

phone_router = APIRouter()
phone_router.include_router(_webhook_router)
phone_router.include_router(_ws_router)

__all__ = ["phone_router"]
