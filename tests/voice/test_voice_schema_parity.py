"""Schema-parity contract: the Pipecat `FunctionSchema`s the voice LLM sees must expose the
same LLM-facing params as the frozen LlamaIndex tool contract (`tests/test_tool_schemas.py`).

The one deliberate difference: voice `book_appointment` drops the `customer` param — the
handler assembles `Customer` from the live case file (`app/voice/tools.py`), so the model
never has to hand back a nested object over the phone. Everything else must match, or the
voice channel and the web channel would present different tools for the same behavior.
"""

from __future__ import annotations

import pytest

from app.voice.session import VoiceSession
from app.voice.tools import build_tools

pytest.importorskip("pipecat.adapters.schemas.function_schema")

# Mirror of tests/test_tool_schemas.py:EXPECTED_TOOL_PARAMS, with voice's book_appointment
# intentionally taking {slot_id, issue_summary} (customer comes from the case file).
VOICE_EXPECTED_TOOL_PARAMS: dict[str, set[str]] = {
    "identify_appliance": {"appliance_type"},
    "record_symptom": {"description", "onset", "error_code", "sound"},
    "get_troubleshooting_steps": {"appliance", "symptom_key"},
    "update_case_file": {"brand", "model", "customer_name", "customer_zip", "customer_email"},
    "find_technicians": {"zip", "appliance_type", "window"},
    "book_appointment": {"slot_id", "issue_summary"},
    "send_image_upload_link": {"email"},
    "check_image_analysis": set(),
}


def _schemas_by_name(monkeypatch) -> dict:
    monkeypatch.delenv("LIBRARY_RAG_ENABLED", raising=False)
    tools_schema, _ = build_tools(VoiceSession.for_call("T"))
    return {s.name: s for s in tools_schema.standard_tools}


def test_voice_exposes_exactly_the_frozen_contract_tools(monkeypatch):
    assert set(_schemas_by_name(monkeypatch)) == set(VOICE_EXPECTED_TOOL_PARAMS)


@pytest.mark.parametrize("tool_name", sorted(VOICE_EXPECTED_TOOL_PARAMS))
def test_voice_tool_schema_params_match_contract(tool_name, monkeypatch):
    schema = _schemas_by_name(monkeypatch)[tool_name]
    assert schema.description, f"{tool_name} needs a description for the LLM"
    actual = set(schema.properties)
    assert actual == VOICE_EXPECTED_TOOL_PARAMS[tool_name], (
        f"{tool_name} voice schema params {sorted(actual)} != frozen contract "
        f"{sorted(VOICE_EXPECTED_TOOL_PARAMS[tool_name])}"
    )
    # required must be a subset of declared properties (no phantom required params).
    assert set(schema.required) <= actual


def test_required_params_match_origin_signatures(monkeypatch):
    schemas = _schemas_by_name(monkeypatch)
    assert set(schemas["identify_appliance"].required) == {"appliance_type"}
    assert set(schemas["record_symptom"].required) == {"description"}  # onset/code/sound optional
    assert set(schemas["get_troubleshooting_steps"].required) == {"appliance", "symptom_key"}
    assert schemas["update_case_file"].required == []  # all fields optional
    assert set(schemas["find_technicians"].required) == {"zip", "appliance_type"}
    assert set(schemas["book_appointment"].required) == {"slot_id", "issue_summary"}
