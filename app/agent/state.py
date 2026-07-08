"""Per-turn tool state, threaded via a ``ContextVar``.

Tool functions (`app/tools/core_tools.py`) must match the frozen call signatures in
`app/contracts.py` exactly — no extra ``ctx``/session parameter leaks into what the LLM
sees. A ``ContextVar`` gives tools implicit access to *this turn's* `CaseFile` without
widening their signature: `app/agent/core.py` sets it once per turn (`asyncio.Task`
creation snapshots the current context, so it propagates correctly through the
workflow's internal steps) and the WS handler never touches it directly.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.contracts import CaseFile

current_case_file: ContextVar[CaseFile] = ContextVar("current_case_file")


def get_case_file() -> CaseFile:
    """Fetch the active turn's case file. Raises if called outside a turn context."""
    return current_case_file.get()
