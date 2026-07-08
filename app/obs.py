"""Structured event logging (specs/features/2026-07-09-observability-tracing).

One line per event, ``key=value``, grep-able: ``wrangler tail | grep event=twilio.``
must read as a complete call story. Correlation ids (session/call/turn) bind once per
call via a contextvar and attach to EVERY event automatically — including events
emitted deep inside llama-index where no call context is in scope.

Logging must never affect the call: ``log_event`` cannot raise (it degrades to a
plain message), and values are flattened to short scalars.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class CallContext:
    session_id: str | None = None
    call_sid: str | None = None
    turn_index: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


_call_context: ContextVar[CallContext | None] = ContextVar("obs_call_context", default=None)


def bind_call_context(
    *,
    session_id: str | None = None,
    call_sid: str | None = None,
    turn_index: int | None = None,
    **extra: object,
) -> CallContext:
    """Bind (or update) the current call's correlation ids for this context."""
    ctx = _call_context.get() or CallContext()
    if session_id is not None:
        ctx.session_id = str(session_id)
    if call_sid is not None:
        ctx.call_sid = call_sid
    if turn_index is not None:
        ctx.turn_index = turn_index
    ctx.extra.update(extra)
    _call_context.set(ctx)
    return ctx


def bound_context() -> CallContext | None:
    return _call_context.get()


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value)
    if " " in text or "=" in text:
        text = '"' + text.replace('"', "'") + '"'
    return text


def log_event(logger: logging.Logger, event: str, /, **fields: object) -> None:
    """Emit one structured event line; never raises."""
    try:
        parts = [f"event={event}"]
        ctx = _call_context.get()
        if ctx is not None:
            if ctx.session_id and "session" not in fields:
                parts.append(f"session={ctx.session_id}")
            if ctx.call_sid and "call" not in fields:
                parts.append(f"call={ctx.call_sid}")
            if ctx.turn_index is not None and "turn" not in fields:
                parts.append(f"turn={ctx.turn_index}")
        parts.extend(f"{key}={_fmt(value)}" for key, value in fields.items() if value is not None)
        logger.info(" ".join(parts))
    except Exception:  # pragma: no cover — the never-break-the-call guarantee
        logger.info("event=%s (unformattable fields)", event)
