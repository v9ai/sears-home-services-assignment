"""Per-turn tool state, threaded via a ``ContextVar``.

Tool functions (`app/tools/core_tools.py`) must match the frozen call signatures in
`app/contracts.py` exactly — no extra ``ctx``/session parameter leaks into what the LLM
sees. A ``ContextVar`` gives tools implicit access to *this turn's* `CaseFile` without
widening their signature: `app/agent/core.py` sets it once per turn (`asyncio.Task`
creation snapshots the current context, so it propagates correctly through the
workflow's internal steps) and the WS handler never touches it directly.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from app.contracts import CaseFile

current_case_file: ContextVar[CaseFile] = ContextVar("current_case_file")

# The active turn's session id (visual tools need it to attach uploads to a session).
# Defaults to None so agent runs without a persisted session (e.g. the eval harness)
# still work — visual tools degrade gracefully when there's no session to attach to.
current_session_id: ContextVar[uuid.UUID | None] = ContextVar("current_session_id", default=None)


def get_case_file() -> CaseFile:
    """Fetch the active turn's case file. Raises if called outside a turn context."""
    return current_case_file.get()


def get_session_id() -> uuid.UUID | None:
    """Fetch the active turn's session id, or None if the turn has no persisted session."""
    return current_session_id.get()


# Per-session offered scheduling slots (task #21). ``find_technicians`` records the slots
# it just offered here so the NEXT turn's system prompt can list them with their refs —
# letting the model book a slot the caller accepts ("the July 11th 3-5 PM one", "the first
# one") without re-searching. Unlike the durable ``CaseFile`` facts, offered slots are
# transient (they go stale the moment availability changes) so they live in session-scoped
# process memory, NOT the persisted case file. One container serves a whole session (demo
# topology), and each new offer for a session replaces the prior one. Keyed by session id;
# ``None`` covers sessionless runs (the eval/adaptive harness).
_offered_slots_by_session: dict[uuid.UUID | None, list[dict[str, str]]] = {}


def set_offered_slots(session_id: uuid.UUID | None, slots: list[dict[str, str]]) -> None:
    """Record the slots just offered for ``session_id``, replacing any prior offer."""
    _offered_slots_by_session[session_id] = slots


def get_offered_slots(session_id: uuid.UUID | None) -> list[dict[str, str]]:
    """The slots most recently offered for ``session_id``, or ``[]`` if none."""
    return _offered_slots_by_session.get(session_id, [])
