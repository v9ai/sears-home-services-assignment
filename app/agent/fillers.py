"""Shared filler/fallback strings (latency-engineering P0-1 prerequisite).

Phone and web speak slightly different wording for the same purpose today — this
module doesn't unify that wording (a product-copy call outside this feature's scope),
it just gives both variants one shared home so `app/agent/tts_cache.py` can cache each
by its exact text instead of the two channels re-defining (and risking re-forking)
their own copies.
"""

from __future__ import annotations

import os

from app.agent.prompts import GREETING

PHONE_TOOL_FILLER = "Let me check that for you."
PHONE_TURN_FAILED_FALLBACK = (
    "I'm sorry, I'm having trouble on my end right now. Could you say that again?"
)
WEB_TOOL_FILLER = "Let me check that for you..."
WEB_TURN_FAILED_FALLBACK = (
    "Sorry, I hit a snag on my end. Could you say that again, or rephrase it for me?"
)

CACHED_STRINGS: tuple[str, ...] = (
    GREETING,
    PHONE_TOOL_FILLER,
    PHONE_TURN_FAILED_FALLBACK,
    WEB_TOOL_FILLER,
    WEB_TURN_FAILED_FALLBACK,
)

FILLER_DEBOUNCE_S: float = float(os.environ.get("FILLER_DEBOUNCE_MS", "250")) / 1000
