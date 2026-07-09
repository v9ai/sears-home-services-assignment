"""Edge behaviors of the voice tool bridge (`app/voice/tools.py`).

Covers the parts of the bridge that aren't plain pass-throughs:
- `book_appointment` assembles `Customer` from the live case file (not from an LLM arg).
- the `_handler` wrapper binds the ContextVars, drops omitted args, and turns any tool
  exception into a spoken-safe string so a tool failure never tears down the call.
"""

from __future__ import annotations

import pytest

from app.agent.state import get_case_file, get_session_id
from app.tools import scheduling_tools
from app.voice import tools as voice_tools
from app.voice.session import VoiceSession

pytest.importorskip("pipecat.services.llm_service")

from types import SimpleNamespace  # noqa: E402


async def _drive(handler, arguments: dict) -> str:
    captured: list = []

    async def result_callback(result, **_kwargs):
        captured.append(result)

    await handler(SimpleNamespace(arguments=arguments, result_callback=result_callback))
    return captured[0]


async def test_book_appointment_assembles_customer_from_case_file(monkeypatch):
    seen: dict = {}

    async def fake_book(*, slot_id, customer, issue_summary):
        seen.update(slot_id=slot_id, customer=customer, issue_summary=issue_summary)
        return "ok"

    # Patch BEFORE build_tools so the handler closes over the fake.
    monkeypatch.setattr(scheduling_tools, "book_appointment", fake_book)

    session = VoiceSession.for_call("T")
    session.case_file.customer.name = "Dana"
    session.case_file.customer.email = "dana@example.com"
    session.case_file.customer.zip = "60614"
    _, handlers = voice_tools.build_tools(session)

    out = await _drive(
        handlers["book_appointment"], {"slot_id": "s1", "issue_summary": "washer won't drain"}
    )
    assert out == "ok"
    assert seen["slot_id"] == "s1"
    assert seen["issue_summary"] == "washer won't drain"
    # customer came from the case file, not from an LLM-supplied nested object.
    assert seen["customer"].name == "Dana"
    assert seen["customer"].email == "dana@example.com"
    assert seen["customer"].zip == "60614"


async def test_handler_wraps_tool_failure_as_spoken_error():
    async def boom(**_kwargs):
        raise RuntimeError("backend down")

    handler = voice_tools._handler(VoiceSession.for_call("T"), boom, arg_names=("x",))
    out = await _drive(handler, {"x": "1"})
    assert "problem" in out.lower()  # the spoken-safe fallback, not an exception


async def test_handler_binds_contextvars_and_drops_omitted_args():
    session = VoiceSession.for_call("T")
    received: dict = {}

    async def probe(**kwargs):
        received.update(kwargs)
        # tools reach session state via the ContextVars bind() sets:
        received["case_file_is_session"] = get_case_file() is session.case_file
        received["session_id"] = get_session_id()
        return "done"

    handler = voice_tools._handler(session, probe, arg_names=("a", "b", "c"))
    out = await _drive(handler, {"a": "x", "b": None})  # b omitted, c absent
    assert out == "done"
    assert received["a"] == "x"
    assert "b" not in received and "c" not in received  # None/absent args dropped
    assert received["case_file_is_session"] is True
    assert received["session_id"] == session.session_id


async def test_contextvars_reset_after_handler():
    """After a handler runs, the ContextVars are reset (no leak across calls)."""
    from app.agent.state import current_case_file

    async def probe(**_kwargs):
        return "ok"

    handler = voice_tools._handler(VoiceSession.for_call("T"), probe, arg_names=())
    await _drive(handler, {})
    # Outside any bind(), get() must raise (the var has no default) — i.e. it was reset.
    with pytest.raises(LookupError):
        current_case_file.get()
