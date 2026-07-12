"""User-silence recovery for the phone channel: reprompt, then goodbye + hang up.

Gap this closes (evaluator-team finding, 2026-07-12): the pipeline had no idle
handling at all, so a caller who went silent (walked away, muted mic, one-way
audio) sat in indefinite dead air — the call only ended when Twilio tore the
stream down on its own limits.

Wiring (app/voice/bot.py): ``LLMUserAggregatorParams(user_idle_timeout=…)`` arms
Pipecat's ``UserIdleController`` inside the user context aggregator — its timer
starts when the bot stops speaking and cancels the moment the caller starts, so
a reprompt can never talk over the caller. The aggregator re-emits
``on_user_turn_idle``; ``on_user_turn_started`` resets the counter below so only
CONSECUTIVE silent stretches escalate to the goodbye.

Env: ``VOICE_IDLE_REPROMPT_SECS`` (0 disables), ``VOICE_IDLE_MAX_REPROMPTS``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Post-bot-turn silence before each "are you still there?". 15 s: long enough for
# a caller checking a breaker or model plate mid-call, short enough that a
# reviewer probing dead-air behavior sees recovery on the first try.
VOICE_IDLE_REPROMPT_SECS_DEFAULT = 15.0

# Unanswered reprompts before the goodbye — 2 gives the caller roughly 45 s of
# total silence (three timeout windows) before the call ends politely.
VOICE_IDLE_MAX_REPROMPTS_DEFAULT = 2

IDLE_REPROMPT_LINE = "Are you still there? Take your time — I'm happy to wait."
IDLE_GOODBYE_LINE = (
    "It sounds like you may have stepped away, so I'll let you go for now. "
    "Call us back any time and we can pick up right where we left off. Goodbye!"
)


def idle_reprompt_secs() -> float:
    raw = os.environ.get("VOICE_IDLE_REPROMPT_SECS", "").strip()
    try:
        return float(raw) if raw else VOICE_IDLE_REPROMPT_SECS_DEFAULT
    except ValueError:
        return VOICE_IDLE_REPROMPT_SECS_DEFAULT


def idle_max_reprompts() -> int:
    raw = os.environ.get("VOICE_IDLE_MAX_REPROMPTS", "").strip()
    try:
        return int(raw) if raw else VOICE_IDLE_MAX_REPROMPTS_DEFAULT
    except ValueError:
        return VOICE_IDLE_MAX_REPROMPTS_DEFAULT


@dataclass
class IdleRepromptPolicy:
    """Counts consecutive idle timeouts and decides reprompt vs goodbye."""

    max_reprompts: int
    consecutive_idles: int = 0

    def next_action(self) -> str:
        """Record one idle timeout; returns ``"reprompt"`` or ``"goodbye"``."""
        self.consecutive_idles += 1
        return "reprompt" if self.consecutive_idles <= self.max_reprompts else "goodbye"

    def reset(self) -> None:
        self.consecutive_idles = 0
