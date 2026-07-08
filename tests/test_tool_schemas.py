"""Regression: every auto-discovered tool must build a valid LlamaIndex FunctionTool
schema, and its LLM-facing parameters must match the frozen contract (COORDINATION §2).

Why this exists: unit tests call tool functions directly and the live-driver tests use a
fake LLM, so nothing bound the *real* tools to the real function-calling schema builder.
A stray `from __future__ import annotations` in a tools module stringized the forward
refs, so LlamaIndex couldn't resolve the type hints when deriving each tool's JSON
schema — crashing `find_technicians`/`book_appointment` on every live agent turn while
every existing test stayed green. This test reproduces exactly that schema-build path.
"""

from __future__ import annotations

import pytest
from llama_index.core.tools import FunctionTool

from app.tools.registry import get_tools

# The frozen tool signatures (COORDINATION.md §2) — the exact LLM-facing parameter set
# each tool must expose. Changing one is constitution-revising, so pinning them here is
# a contract test, not incidental coupling. A `Context`/session param, if any, is
# auto-injected and must NOT appear in the schema.
EXPECTED_TOOL_PARAMS: dict[str, set[str]] = {
    "identify_appliance": {"appliance_type"},
    "record_symptom": {"description", "onset", "error_code", "sound"},
    "get_troubleshooting_steps": {"appliance", "symptom_key"},
    "update_case_file": {"brand", "model", "customer_name", "customer_zip", "customer_email"},
    "find_technicians": {"zip", "appliance_type", "window"},
    "book_appointment": {"slot_id", "customer", "issue_summary"},
    "send_image_upload_link": {"email"},
    "check_image_analysis": set(),
}


def _tools_by_name() -> dict[str, object]:
    return {FunctionTool.from_defaults(fn=fn).metadata.name: fn for fn in get_tools()}


def test_registry_exposes_exactly_the_frozen_contract_tools() -> None:
    assert set(_tools_by_name()) == set(EXPECTED_TOOL_PARAMS)


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_PARAMS))
def test_tool_builds_valid_function_schema(tool_name: str) -> None:
    fn = _tools_by_name()[tool_name]

    # This is the exact call path that crashed with stringized forward refs.
    tool = FunctionTool.from_defaults(fn=fn)
    schema = tool.metadata.get_parameters_dict()

    assert tool.metadata.description, f"{tool_name} needs a docstring for the LLM"
    assert schema.get("type") == "object"
    actual_params = set(schema.get("properties", {}))
    assert actual_params == EXPECTED_TOOL_PARAMS[tool_name], (
        f"{tool_name} schema params {sorted(actual_params)} != frozen contract "
        f"{sorted(EXPECTED_TOOL_PARAMS[tool_name])} — a broken schema build (e.g. "
        f"stringized forward refs) or a contract drift"
    )
