"""Prompt static assert for P2-1 (latency-engineering): independent tool calls for one
caller turn must be issued together in a single LLM response — each extra round trip
is caller-facing dead air (measured: 2-tool turns dominated the failing e2e
submit_to_first_token in data/latency/20260709T211909Z.json)."""

from __future__ import annotations

from llama_index.core.memory import ChatMemoryBuffer

from app.agent.core import ToolInvoked, run_turn
from app.agent.prompts import NON_NEGOTIABLES, build_system_prompt
from app.agent.trace import TurnTrace
from app.contracts import CaseFile
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


async def _drain(agen):
    return [event async for event in agen]


def test_non_negotiables_direct_parallel_tool_calls():
    assert "single response" in NON_NEGOTIABLES
    assert "round trip" in NON_NEGOTIABLES


def test_non_negotiables_frame_extra_round_trips_as_dead_air():
    # The drift guard for *why* the rule exists — if this rationale is deleted the rule
    # reads as arbitrary and a future edit is likely to relax it.
    assert "dead air" in NON_NEGOTIABLES
    assert "single response" in NON_NEGOTIABLES


def test_parallel_tool_guidance_reaches_the_system_prompt():
    prompt = build_system_prompt(CaseFile())
    assert "ALL the independent tool calls" in prompt


# --- Functional: parallel calls execute in one turn and map back correctly ----------


async def test_parallel_tool_calls_in_one_turn_execute_and_map_to_distinct_ids():
    """Two independent tool calls issued together in a single LLM response must both
    execute, both mutate the case file, and both be attributed by their own tool_id in
    the trace (the per-tool timing dict is keyed by id, so a collision would drop one)."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "identify_appliance", {"appliance_type": "washer"}, tool_id="call_a"
                    ),
                    ScriptedToolCall(
                        "record_symptom",
                        {"description": "loud noise", "onset": "today"},
                        tool_id="call_b",
                    ),
                ]
            ),
            ScriptedTurn(text="Done — a washer making a loud noise since today."),
        ]
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    trace = TurnTrace(channel="web", scenario_id="parallel", turn_index=0)
    trace.mark("t0")

    events = await _drain(run_turn(case_file, memory, "washer is loud", llm=llm, trace=trace))

    tool_names = [e.tool_name for e in events if isinstance(e, ToolInvoked)]
    assert tool_names == ["identify_appliance", "record_symptom"]
    # Both mutations landed from the single round.
    assert case_file.appliance_type == "washer"
    assert [s.description for s in case_file.symptoms] == ["loud noise"]
    # Both tools are attributed independently in the rollup extras.
    record = trace.to_record()
    assert "identify_appliance:" in record["tool_ms"]
    assert "record_symptom:" in record["tool_ms"]
    assert record["tool_calls"] == 2


async def test_parallel_same_tool_twice_records_two_distinct_entries():
    """Two `record_symptom` calls in one turn must produce two case-file entries — the
    results must not collapse into one (id-keyed dispatch, not name-keyed)."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "record_symptom", {"description": "leaking water"}, tool_id="s1"
                    ),
                    ScriptedToolCall("record_symptom", {"description": "loud noise"}, tool_id="s2"),
                ]
            ),
            ScriptedTurn(text="Recorded both."),
        ]
    )
    case_file = CaseFile(appliance_type="washer")
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    await _drain(run_turn(case_file, memory, "it leaks and it's loud", llm=llm))

    assert [s.description for s in case_file.symptoms] == ["leaking water", "loud noise"]
