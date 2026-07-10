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

import json

import pytest
from llama_index.core.tools import FunctionTool

from app.contracts import Appliance
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

# The frozen *required* parameter set per tool — the subset the model must supply.
# A drift here (an optional field becoming required, or vice versa) silently changes what
# the model is forced to invent, so it's pinned exactly like the parameter set above. A
# tool with no required params (all optional / none) maps to the empty set.
EXPECTED_REQUIRED_PARAMS: dict[str, set[str]] = {
    "identify_appliance": {"appliance_type"},
    "record_symptom": {"description"},
    "get_troubleshooting_steps": {"appliance", "symptom_key"},
    "update_case_file": set(),
    "find_technicians": {"zip", "appliance_type"},
    "book_appointment": {"slot_id", "customer", "issue_summary"},
    "send_image_upload_link": {"email"},
    "check_image_analysis": set(),
}

# Parameters whose contract type is a closed vocabulary (a ``Literal``/enum) — the schema
# must expose the full option list so the model can't pass an out-of-vocabulary value.
# ``find_technicians.appliance_type`` is the ``Appliance`` literal (contracts.py); if the
# six-appliance list ever drifts from the contract this guard fails.
_APPLIANCE_OPTIONS = set(Appliance.__args__)  # type: ignore[attr-defined]
EXPECTED_ENUM_PARAMS: dict[tuple[str, str], set[str]] = {
    ("find_technicians", "appliance_type"): _APPLIANCE_OPTIONS,
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


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_REQUIRED_PARAMS))
def test_tool_required_params_match_frozen_contract(tool_name: str) -> None:
    """The *required* subset is part of the frozen contract: flipping an optional field
    to required (or the reverse) changes what the model is forced to supply/invent."""
    fn = _tools_by_name()[tool_name]
    schema = FunctionTool.from_defaults(fn=fn).metadata.get_parameters_dict()

    required = set(schema.get("required") or [])
    assert required == EXPECTED_REQUIRED_PARAMS[tool_name], (
        f"{tool_name} required params {sorted(required)} != frozen contract "
        f"{sorted(EXPECTED_REQUIRED_PARAMS[tool_name])}"
    )
    # Required params must be a subset of the declared params — a required name that
    # isn't even in `properties` would be an unsatisfiable schema.
    assert required <= EXPECTED_TOOL_PARAMS[tool_name]


@pytest.mark.parametrize(("tool_name", "param"), sorted(EXPECTED_ENUM_PARAMS))
def test_closed_vocabulary_params_expose_the_full_enum(tool_name: str, param: str) -> None:
    """A ``Literal``-typed contract param must surface its whole option set in the schema,
    so the function-calling model is constrained to valid values (no free-text drift)."""
    fn = _tools_by_name()[tool_name]
    schema = FunctionTool.from_defaults(fn=fn).metadata.get_parameters_dict()

    spec = schema["properties"][param]
    enum = set(spec.get("enum") or [])
    assert enum == EXPECTED_ENUM_PARAMS[(tool_name, param)], (
        f"{tool_name}.{param} enum {sorted(enum)} != the frozen Appliance vocabulary "
        f"{sorted(EXPECTED_ENUM_PARAMS[(tool_name, param)])} — contract drift"
    )


def test_no_tool_leaks_a_context_or_session_parameter() -> None:
    """The per-turn case file / session id reach tools via a ContextVar, never as an
    LLM-visible parameter (app/agent/state.py). A schema exposing one of these names would
    mean the model is being asked to supply ambient state it must never see."""
    forbidden = {"ctx", "context", "session", "session_id", "case_file", "casefile", "self"}
    for tool_name, fn in _tools_by_name().items():
        schema = FunctionTool.from_defaults(fn=fn).metadata.get_parameters_dict()
        leaked = set(schema.get("properties", {})) & forbidden
        assert not leaked, f"{tool_name} leaks ambient-state param(s) into its schema: {leaked}"


# --- Adversarial surface guards -------------------------------------------------------
# The schema is the contract a function-calling model is held to; these pin that the
# surface can't be widened to smuggle extra args, and that it always serializes cleanly.


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_PARAMS))
def test_tool_schema_is_json_serializable_and_not_open_ended(tool_name: str) -> None:
    fn = _tools_by_name()[tool_name]
    schema = FunctionTool.from_defaults(fn=fn).metadata.get_parameters_dict()

    # Must round-trip as JSON (it's uploaded to the model as JSON every round).
    assert json.loads(json.dumps(schema)) == schema
    # additionalProperties must not be True — an open-ended object schema would invite a
    # model (or a tampered tool call) to attach arbitrary extra keys the tool never
    # declared. Absent (pydantic default) or False both satisfy this.
    assert schema.get("additionalProperties", False) is not True


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_PARAMS))
def test_tool_rejects_an_injected_extra_argument(tool_name: str) -> None:
    """A malformed/tampered tool call carrying an argument the schema never declared is
    rejected at the Python call boundary (TypeError), before the tool body runs — so the
    frozen parameter set can't be widened by injecting keys. The bad kwarg raises at call
    time, so no coroutine is created (nothing to await)."""
    fn = _tools_by_name()[tool_name]
    with pytest.raises(TypeError):
        fn(**{"__extra_injected_arg__": "x"})
