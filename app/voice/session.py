"""Per-call session state for the Pipecat voice bot.

This is the Pipecat-side equivalent of the live half of
`app/agent/session_store.py:SessionState`. Two memory layers, exactly as the LlamaIndex
agent had them (see that module's inventory):

1. **Verbatim dialogue history** — owned by Pipecat's context aggregator (the
   `context_aggregator.user()/assistant()` pair in `app/voice/bot.py`), which is the
   Pipecat replacement for LlamaIndex's `ChatMemoryBuffer`. We do not keep a second copy.
2. **Structured "never re-ask" memory** — the `CaseFile` here, injected into the system
   prompt every turn by `SystemPromptRefreshProcessor` (mirrors `app/agent/core.py`
   rebuilding the prompt from the live case file each turn).

The ported tools (`app/voice/tools.py`) read the live `CaseFile` / session id through the
SAME `ContextVar`s the original tools use (`app/agent/state.py`) — `bind()` sets them for
the duration of a tool call so `app.tools.*` needs no modification.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.agent.state import current_case_file, current_session_id
from app.contracts import CaseFile

# Stable namespace so a given Twilio CallSid always maps to the same session UUID
# (lets scheduling/visual tools attach work to *this* call — and closes the
# `book_appointment(session_id=None)` gap noted in app/tools/scheduling_tools.py).
_CALL_NAMESPACE = uuid.UUID("5e4a5b8c-0000-4000-8000-000000000001")


@dataclass
class VoiceSession:
    """Structured session memory for one phone call."""

    call_sid: str | None = None
    case_file: CaseFile = field(default_factory=CaseFile)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def for_call(cls, call_sid: str | None) -> VoiceSession:
        session_id = uuid.uuid5(_CALL_NAMESPACE, call_sid) if call_sid else uuid.uuid4()
        return cls(call_sid=call_sid, case_file=CaseFile(), session_id=session_id)

    @contextmanager
    def bind(self) -> Iterator[None]:
        """Bind this call's `CaseFile` + session id to the per-turn ContextVars the
        ported `app.tools.*` functions read (`app/agent/state.get_case_file` /
        `get_session_id`). Used around each tool-handler invocation in
        `app/voice/tools.py`, replicating what `app/agent/core.run_turn` does per turn.
        """
        cf_token = current_case_file.set(self.case_file)
        sid_token = current_session_id.set(self.session_id)
        try:
            yield
        finally:
            # Reset in the same task/context that set them (see the equivalent
            # finally in app/agent/core.run_turn for why this ordering matters).
            current_case_file.reset(cf_token)
            current_session_id.reset(sid_token)
