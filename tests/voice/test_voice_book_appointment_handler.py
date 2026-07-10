"""The voice `book_appointment` Pipecat handler + the generic tool-handler error path
(`app/voice/tools.py`).

`book_appointment` is the one tool whose handler is hand-written rather than built by the
shared `_handler` factory: it assembles the `Customer` from the live case file (never asks
the LLM for a nested object over voice), runs the origin `scheduling_tools.book_appointment`
inside `session.bind()`, and turns any failure into a spoken-safe error JSON. These tests
drive the handler with a fake `FunctionCallParams` (a `SimpleNamespace`, as in
`tests/voice/test_voice_port.py`) and monkeypatch the origin function, so no DB is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pipecat.services.llm_service")

from app.tools import scheduling_tools  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402
from app.voice.tools import build_tools  # noqa: E402


async def _drive(handler, arguments: dict) -> str:
    captured: list[str] = []

    async def result_callback(result, **_kwargs):
        captured.append(result)

    await handler(SimpleNamespace(arguments=arguments, result_callback=result_callback))
    assert len(captured) == 1  # every handler must answer exactly once
    return captured[0]


def _handlers(session: VoiceSession) -> dict:
    _schema, handlers = build_tools(session)
    return handlers


# --- book_appointment handler --------------------------------------------------------


async def test_book_appointment_assembles_customer_from_case_file(monkeypatch):
    """The handler must NOT take a Customer from the LLM — it builds one from the case file
    the caller already filled this call, and forwards slot_id/issue_summary verbatim."""
    session = VoiceSession.for_call("CAbook1")
    session.case_file.customer.name = "Dana Lee"
    session.case_file.customer.zip = "60614"
    session.case_file.customer.email = "dana@example.com"

    seen: dict = {}

    async def fake_book(*, slot_id, customer, issue_summary):
        seen["slot_id"] = slot_id
        seen["customer"] = customer
        seen["issue_summary"] = issue_summary
        return '{"status": "confirmed", "appointment_id": "AP1"}'

    monkeypatch.setattr(scheduling_tools, "book_appointment", fake_book)

    result = await _drive(
        _handlers(session)["book_appointment"],
        {"slot_id": "slot_1", "issue_summary": "dryer won't heat"},
    )

    assert result == '{"status": "confirmed", "appointment_id": "AP1"}'
    assert seen["slot_id"] == "slot_1"
    assert seen["issue_summary"] == "dryer won't heat"
    # Customer assembled from the live case file, not the (absent) LLM argument.
    assert seen["customer"].name == "Dana Lee"
    assert seen["customer"].zip == "60614"
    assert seen["customer"].email == "dana@example.com"


async def test_book_appointment_binds_session_contextvars(monkeypatch):
    """The origin reads the bound session id via ContextVars — the handler must run inside
    `session.bind()` so attribution (appointments.session_id FK) lands on this call."""
    from app.agent.state import get_session_id

    session = VoiceSession.for_call("CAbook2")
    seen: dict = {}

    async def fake_book(*, slot_id, customer, issue_summary):
        seen["bound_session_id"] = get_session_id()
        return '{"status": "confirmed"}'

    monkeypatch.setattr(scheduling_tools, "book_appointment", fake_book)

    await _drive(
        _handlers(session)["book_appointment"],
        {"slot_id": "slot_1", "issue_summary": "oven sparking"},
    )

    assert seen["bound_session_id"] == session.session_id


async def test_book_appointment_error_is_turned_into_spoken_safe_json(monkeypatch):
    """A raising origin must not tear down the call: the handler returns a fixed error JSON
    (not the raw exception) and still answers via the result callback."""
    session = VoiceSession.for_call("CAbook3")

    async def boom(*, slot_id, customer, issue_summary):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(scheduling_tools, "book_appointment", boom)

    result = await _drive(
        _handlers(session)["book_appointment"],
        {"slot_id": "slot_1", "issue_summary": "washer leaking"},
    )

    import json

    payload = json.loads(result)
    assert payload["status"] == "error"
    assert "retry" in payload["message"].lower()


async def test_book_appointment_passes_through_slot_taken(monkeypatch):
    """A non-exception 'slot_taken' result flows straight back to the model unchanged."""
    session = VoiceSession.for_call("CAbook4")

    async def taken(*, slot_id, customer, issue_summary):
        return '{"status": "slot_taken", "alternatives": []}'

    monkeypatch.setattr(scheduling_tools, "book_appointment", taken)

    result = await _drive(
        _handlers(session)["book_appointment"],
        {"slot_id": "slot_9", "issue_summary": "dishwasher error"},
    )

    assert result == '{"status": "slot_taken", "alternatives": []}'


# --- generic _handler error path (app/voice/tools.py:58-60) --------------------------


async def test_generic_handler_error_is_swallowed_into_a_spoken_string(monkeypatch):
    """The shared `_handler` factory wraps every other tool: a raising origin becomes a
    spoken-safe apology string, keeping the call alive (same resilience as the origin loop)."""
    session = VoiceSession.for_call("CAtool-err")

    async def boom(*args, **kwargs):
        raise ValueError("provider down")

    monkeypatch.setattr(scheduling_tools, "find_technicians", boom)

    result = await _drive(
        _handlers(session)["find_technicians"],
        {"zip": "60614", "appliance_type": "dryer", "window": "morning"},
    )

    assert isinstance(result, str)
    assert "problem" in result.lower()  # the fixed apology, not the raw exception
    assert "provider down" not in result


async def test_generic_handler_drops_none_valued_arguments(monkeypatch):
    """`_handler` forwards only the args the LLM actually supplied — a `None` (omitted
    optional like `window`) must not be passed, so the origin's own default applies."""
    session = VoiceSession.for_call("CAtool-none")
    seen: dict = {}

    async def spy(**kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(scheduling_tools, "find_technicians", spy)

    await _drive(
        _handlers(session)["find_technicians"],
        {"zip": "60614", "appliance_type": "dryer", "window": None},
    )

    assert "window" not in seen  # None-valued arg dropped
    assert seen == {"zip": "60614", "appliance_type": "dryer"}
