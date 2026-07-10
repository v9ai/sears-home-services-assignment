"""Voice tool-bridge fidelity (bugfix-loop T19, audit04 gaps 1–3).

Two blind spots in `app/voice/tools.py`: (a) nothing compared each Pipecat
FunctionSchema against its origin `app.tools.*` signature, so a renamed
parameter or dropped enum would silently break function calling; (b) the
ported visual and RAG handlers were registered by name but never executed.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from typing import get_args

import pytest

from app.contracts import Appliance
from app.email.backend import ConsoleEmailBackend, set_email_backend
from app.knowledge.library_store import LibraryHit
from app.knowledge.library_store import set_store as set_library_store
from app.tools import core_tools, library_tools, scheduling_tools, visual_tools
from app.uploads.store import InMemoryUploadStore
from app.uploads.store import set_store as set_upload_store

pytest.importorskip("pipecat.frames.frames")
from app.voice.session import VoiceSession  # noqa: E402
from app.voice.tools import build_tools  # noqa: E402

APPLIANCES = list(get_args(Appliance))

# schema name -> origin function. book_appointment and update_case_file are
# documented exceptions (customer assembled from the case file; **fields).
_MIRRORED_ORIGINS = {
    "identify_appliance": core_tools.identify_appliance,
    "record_symptom": core_tools.record_symptom,
    "get_troubleshooting_steps": core_tools.get_troubleshooting_steps,
    "find_technicians": scheduling_tools.find_technicians,
    "send_image_upload_link": visual_tools.send_image_upload_link,
    "check_image_analysis": visual_tools.check_image_analysis,
}


def _schemas(session: VoiceSession) -> dict[str, object]:
    tools_schema, _ = build_tools(session)
    return {s.name: s for s in tools_schema.standard_tools}


def _origin_params(fn) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(fn).parameters)


def test_every_mirrored_schema_matches_its_origin_signature() -> None:
    schemas = _schemas(VoiceSession.for_call("T19"))
    for name, origin in _MIRRORED_ORIGINS.items():
        schema = schemas[name]
        params = _origin_params(origin)
        assert set(schema.properties) == set(params), (
            f"{name}: schema properties drifted from the origin signature"
        )
        required_in_origin = {
            p_name
            for p_name, p in params.items()
            if p.default is inspect.Parameter.empty
        }
        assert set(schema.required) == required_in_origin, (
            f"{name}: schema required set drifted from the origin defaults"
        )


def test_book_appointment_schema_is_origin_minus_the_assembled_customer() -> None:
    schemas = _schemas(VoiceSession.for_call("T19"))
    origin = _origin_params(scheduling_tools.book_appointment)
    assert set(schemas["book_appointment"].properties) == set(origin) - {"customer"}
    assert set(schemas["book_appointment"].required) == {"slot_id", "issue_summary"}


def test_every_enum_in_the_bridge_is_the_six_appliance_vocabulary() -> None:
    schemas = _schemas(VoiceSession.for_call("T19"))
    enums = [
        (name, prop_name, prop["enum"])
        for name, schema in schemas.items()
        for prop_name, prop in schema.properties.items()
        if "enum" in prop
    ]
    assert enums, "expected at least the appliance enums"
    for name, prop_name, values in enums:
        assert values == APPLIANCES, f"{name}.{prop_name} enum drifted"


def test_update_case_file_schema_required_is_empty_partial_update() -> None:
    schemas = _schemas(VoiceSession.for_call("T19"))
    schema = schemas["update_case_file"]
    assert schema.required == []
    assert set(schema.properties) == {
        "brand",
        "model",
        "customer_name",
        "customer_zip",
        "customer_email",
    }


# --- ported handler execution (visual + RAG) ---------------------------------------


async def _drive(handler, arguments: dict) -> str:
    captured: list[str] = []

    async def result_callback(result, **_kwargs):
        captured.append(result)

    await handler(SimpleNamespace(arguments=arguments, result_callback=result_callback))
    return captured[0]


_APOLOGY = "Sorry, I hit a problem doing that"


@pytest.fixture
def visual_seams():
    set_upload_store(InMemoryUploadStore())
    backend = ConsoleEmailBackend()
    set_email_backend(backend)
    return backend


async def test_send_image_upload_link_handler_binds_session_and_sends(visual_seams) -> None:
    session = VoiceSession.for_call("CA-T19-visual")
    _, handlers = build_tools(session)
    result = await _drive(
        handlers["send_image_upload_link"], {"email": "caller@example.com"}
    )
    assert _APOLOGY not in result
    assert visual_seams.sent, "the ported handler must reach the email backend"
    assert visual_seams.sent[0]["to"] == "caller@example.com"
    assert "/upload/" in visual_seams.sent[0]["body"]
    # The bind() seam attributed the upload to THIS call's session.
    from app.uploads.store import get_store

    record = await get_store().latest_for_session(session.session_id)
    assert record is not None
    # And the origin tool wrote the confirmed email back onto the case file.
    assert session.case_file.customer.email == "caller@example.com"


async def test_check_image_analysis_handler_reports_pending_upload(visual_seams) -> None:
    session = VoiceSession.for_call("CA-T19-visual")
    _, handlers = build_tools(session)
    await _drive(handlers["send_image_upload_link"], {"email": "caller@example.com"})
    result = await _drive(handlers["check_image_analysis"], {})
    assert _APOLOGY not in result
    assert "photo" in result.lower() or "upload" in result.lower()


async def test_check_image_analysis_handler_with_no_upload(visual_seams) -> None:
    session = VoiceSession.for_call("CA-T19-none")
    _, handlers = build_tools(session)
    result = await _drive(handlers["check_image_analysis"], {})
    assert result == "No photo upload has been requested yet for this call."


async def test_library_handler_executes_the_origin_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("LIBRARY_RAG_ENABLED", "1")
    hit = LibraryHit(
        text="Clean the pump filter monthly to avoid drain clogs.",
        score=0.92,
        appliance="washer",
        symptom_key="wont_drain",
        source="general_maintenance_tips.md",
        safety=False,
    )

    class _FakeStore:
        def __init__(self) -> None:
            self.last_query: str | None = None

        def retrieve(self, query: str, k: int = 3) -> list[LibraryHit]:
            self.last_query = query
            return [hit]

    fake = _FakeStore()
    set_library_store(fake)
    try:
        session = VoiceSession.for_call("CA-T19-rag")
        _, handlers = build_tools(session)
        assert "search_appliance_library" in handlers
        result = await _drive(
            handlers["search_appliance_library"], {"query": "washer won't drain"}
        )
        assert _APOLOGY not in result
        assert fake.last_query == "washer won't drain"
        assert "pump filter" in result
    finally:
        set_library_store(None)
