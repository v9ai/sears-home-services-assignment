"""Per-call metadata + the session-recording seam.

The bridge needs to create a ``channel='phone'`` session row and capture the caller
number (requirements.md, plan.md group 3) -- but ``app/db/models_core.py`` (the
``sessions`` table) belongs to ``voice-diagnostic-core``, not this feature
(COORDINATION.md §3). ``SessionRecorder`` is the seam: this feature codes and tests
against it standalone (``InMemorySessionRecorder``); at integration, the lead wires a
real implementation backed by the ``sessions`` repo. Flagged in plan.md Integration
deltas.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class PhoneCallContext:
    """Identifying info pulled from the Twilio ``start`` event's ``customParameters``
    (populated by the ``<Parameter>`` elements the webhook adds -- see ``twiml.py``).

    ``channel`` is always ``"phone"`` here (the ``sessions.channel`` CHECK constraint's
    other value, ``"web"``, is the Phase 1 WS bridge) -- carried explicitly so the
    integration wiring into the real ``sessions`` repo has an unambiguous value to
    write, rather than a convention implied only by "this recorder is the phone one."
    """

    call_sid: str | None = None
    stream_sid: str | None = None
    caller_number: str | None = None
    called_number: str | None = None
    session_id: str | None = None
    channel: str = "phone"
    # specs/features/2026-07-08-call-recording-replay: one shared counter per call,
    # so the caller-wav-at-STT hook (app/phone/routes.py) and the agent-wav-at-TTS
    # hook (app/phone/real_agent.py) never collide on a recorded audio file name.
    audio_seq: itertools.count = field(default_factory=lambda: itertools.count(1))


@runtime_checkable
class SessionRecorder(Protocol):
    """Creates/attaches the ``channel='phone'`` session for a call."""

    async def start_session(self, context: PhoneCallContext) -> str:
        """Persist (or stand in for) a new phone session; returns its session id."""
        ...

    async def end_session(self, session_id: str) -> None: ...


@dataclass
class InMemorySessionRecorder:
    """Default standalone recorder -- no DB, just tracks ids for tests/dev runs."""

    _sessions: dict[str, PhoneCallContext] = field(default_factory=dict)
    _counter: int = 0

    async def start_session(self, context: PhoneCallContext) -> str:
        self._counter += 1
        session_id = context.call_sid or f"phone-session-{self._counter}"
        context.session_id = session_id
        self._sessions[session_id] = context
        return session_id

    async def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
