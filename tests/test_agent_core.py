"""Text-only harness proving the real agent loop end to end (plan.md group 4).

Drives the actual `AgentWorkflow` + `FunctionAgent` + `core_tools` + case-file wiring
against a scripted `FakeFunctionCallingLLM` (no live `OPENAI_API_KEY`/network needed),
per COORDINATION.md §4's stub-seam spirit applied to this feature's own critical path.
"""

from __future__ import annotations

from llama_index.core.memory import ChatMemoryBuffer

from app.agent.core import SentenceReady, ToolInvoked, TurnComplete, run_turn
from app.agent.trace import TurnTrace
from app.contracts import CaseFile
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


async def _drain(agen):
    events = []
    async for event in agen:
        events.append(event)
    return events


async def test_turn_with_tool_calls_then_text_updates_case_file() -> None:
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="identify_appliance", tool_kwargs={"appliance_type": "washer"}
                    ),
                ]
            ),
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="record_symptom",
                        tool_kwargs={"description": "grinding noise", "onset": "yesterday"},
                    ),
                ]
            ),
            ScriptedTurn(text="Got it, a washer with a grinding noise since yesterday."),
        ]
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    events = await _drain(
        run_turn(case_file, memory, "my washer is making a grinding noise", llm=llm)
    )

    tool_events = [e for e in events if isinstance(e, ToolInvoked)]
    sentence_events = [e for e in events if isinstance(e, SentenceReady)]
    complete_events = [e for e in events if isinstance(e, TurnComplete)]

    assert [e.tool_name for e in tool_events] == ["identify_appliance", "record_symptom"]
    assert sentence_events[-1].text == "Got it, a washer with a grinding noise since yesterday."
    assert len(complete_events) == 1

    assert case_file.appliance_type == "washer"
    assert len(case_file.symptoms) == 1
    assert case_file.symptoms[0].description == "grinding noise"


async def test_case_file_mutations_do_not_leak_across_turns() -> None:
    """The contextvar must be scoped to a single turn, not leak into a concurrent one."""
    llm_a = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="identify_appliance", tool_kwargs={"appliance_type": "oven"}
                    )
                ]
            ),
            ScriptedTurn(text="Oven it is."),
        ]
    )
    llm_b = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="identify_appliance", tool_kwargs={"appliance_type": "dryer"}
                    )
                ]
            ),
            ScriptedTurn(text="Dryer it is."),
        ]
    )
    case_file_a = CaseFile()
    case_file_b = CaseFile()
    memory_a = ChatMemoryBuffer.from_defaults(llm=llm_a)
    memory_b = ChatMemoryBuffer.from_defaults(llm=llm_b)

    await _drain(run_turn(case_file_a, memory_a, "oven trouble", llm=llm_a))
    await _drain(run_turn(case_file_b, memory_b, "dryer trouble", llm=llm_b))

    assert case_file_a.appliance_type == "oven"
    assert case_file_b.appliance_type == "dryer"


async def test_safety_symptom_key_halts_with_escalation_text() -> None:
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="get_troubleshooting_steps",
                        tool_kwargs={"appliance": "oven", "symptom_key": "safety_gas_smell"},
                    )
                ]
            ),
            ScriptedTurn(text="Please shut off the gas and step outside; I can send a technician."),
        ]
    )
    case_file = CaseFile(appliance_type="oven")
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    await _drain(run_turn(case_file, memory, "I smell gas", llm=llm))

    assert case_file.safety_flag is True


async def test_run_turn_stamps_trace_when_passed() -> None:
    llm = FakeFunctionCallingLLM(script=[ScriptedTurn(text="Sure, I can help with that.")])
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    trace = TurnTrace(channel="web")

    await _drain(run_turn(case_file, memory, "hello", llm=llm, trace=trace))

    assert "first_token" in trace.marks
    assert "first_sentence_ready" in trace.marks


async def test_run_turn_without_trace_behaves_like_before() -> None:
    llm = FakeFunctionCallingLLM(script=[ScriptedTurn(text="Sure, I can help with that.")])
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    events = await _drain(run_turn(case_file, memory, "hello", llm=llm))

    sentence_events = [e for e in events if isinstance(e, SentenceReady)]
    assert sentence_events[-1].text == "Sure, I can help with that."


async def test_pre_tool_acknowledgment_streams_before_the_tool_round_trip() -> None:
    """P0-4 enforcement (latency-engineering): a short spoken acknowledgment in the
    same LLM round as the tool calls must reach the caller BEFORE the tool round
    trips — pre-fix it sat under the 40-char first-clause floor and only flushed with
    the next LLM response, i.e. after all the dead air it exists to cover."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                text="Got it — one moment.",
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="identify_appliance", tool_kwargs={"appliance_type": "washer"}
                    ),
                ],
            ),
            ScriptedTurn(text="Your washer is on file; let's look at that noise."),
        ]
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    events = await _drain(run_turn(case_file, memory, "my washer is grinding", llm=llm))

    first_sentence_index = next(i for i, e in enumerate(events) if isinstance(e, SentenceReady))
    first_tool_index = next(i for i, e in enumerate(events) if isinstance(e, ToolInvoked))
    assert events[first_sentence_index].text == "Got it — one moment."
    assert first_sentence_index < first_tool_index
