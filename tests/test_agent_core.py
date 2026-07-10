"""Text-only harness proving the real agent loop end to end (plan.md group 4).

Drives the actual `AgentWorkflow` + `FunctionAgent` + `core_tools` + case-file wiring
against a scripted `FakeFunctionCallingLLM` (no live `OPENAI_API_KEY`/network needed),
per COORDINATION.md §4's stub-seam spirit applied to this feature's own critical path.
"""

from __future__ import annotations

from llama_index.core.memory import ChatMemoryBuffer

from app.agent.core import SentenceReady, ToolInvoked, TurnComplete, run_turn
from app.agent.prompts import build_system_prompt
from app.agent.trace import TurnTrace
from app.contracts import CaseFile
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


async def _drain(agen):
    events = []
    async for event in agen:
        events.append(event)
    return events


def _tool_then_text(*calls: ScriptedToolCall, text: str) -> list[ScriptedTurn]:
    """A one-caller-turn script: a tool round (the given calls) then a text round."""
    return [ScriptedTurn(tool_calls=list(calls)), ScriptedTurn(text=text)]


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


async def test_trace_attributes_per_tool_wall_time() -> None:
    """t1 (loop-v2 i12): tool-turn tails must be attributable — each executed tool
    lands in the trace extras as `tool_ms` (name:ms) with a `tool_ms_total` rollup."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        tool_name="identify_appliance", tool_kwargs={"appliance_type": "washer"}
                    ),
                ]
            ),
            ScriptedTurn(text="Got it — a washer."),
        ]
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    trace = TurnTrace(channel="web", scenario_id="t1_tool_ms", turn_index=0)
    trace.mark("t0")

    await _drain(run_turn(case_file, memory, "washer is broken", llm=llm, trace=trace))

    record = trace.to_record()
    assert record["tool_ms"] is not None
    assert "identify_appliance:" in record["tool_ms"]
    assert record["tool_ms_total"] is not None and record["tool_ms_total"] >= 0


# --- Conversation memory: the never-re-ask contract, made structural ----------------
# The CaseFile IS this product's conversation memory (app/contracts.py: "Structured
# session memory — the never-re-ask non-negotiable made structural"). It persists at the
# call site across `run_turn` calls, and `build_system_prompt` re-injects it every turn,
# so a fact captured on one turn is in the model's context on every later turn.


async def _run(case_file: CaseFile, *calls: ScriptedToolCall, text: str, user: str = "x") -> None:
    """Drive one caller turn against a fresh fake LLM, mutating the shared case file."""
    llm = FakeFunctionCallingLLM(script=_tool_then_text(*calls, text=text))
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    await _drain(run_turn(case_file, memory, user, llm=llm))


async def test_captured_facts_persist_across_turns_and_reach_the_next_prompt() -> None:
    """A washer, a symptom, and the caller's identity captured over three turns must all
    remain in the case file AND appear in the very next turn's system prompt — the
    structural guarantee behind "never re-ask" (Tier 1 Conversation Memory)."""
    case_file = CaseFile()

    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "washer"}),
        text="Got it, a washer.",
        user="my washer is broken",
    )
    await _run(
        case_file,
        ScriptedToolCall("record_symptom", {"description": "grinding noise", "onset": "yesterday"}),
        text="Noted the grinding.",
        user="it grinds",
    )
    await _run(
        case_file,
        ScriptedToolCall(
            "update_case_file",
            {
                "customer_name": "Jordan Rivera",
                "customer_zip": "60614",
                "customer_email": "jordan.rivera@example.com",
            },
        ),
        text="Thanks, Jordan.",
        user="I'm Jordan, 60614, jordan.rivera@example.com",
    )

    # Every fact accumulated into the single shared case file.
    assert case_file.appliance_type == "washer"
    assert [s.description for s in case_file.symptoms] == ["grinding noise"]
    assert case_file.customer.name == "Jordan Rivera"
    assert case_file.customer.zip == "60614"
    assert case_file.customer.email == "jordan.rivera@example.com"

    # The next turn's prompt carries all of them plus the never-re-ask rule, so the model
    # is told, in-context, not to ask for any of them again.
    prompt = build_system_prompt(case_file)
    assert "NEVER RE-ASK" in prompt
    for fact in ("washer", "grinding noise", "Jordan Rivera", "60614", "jordan.rivera@example.com"):
        assert fact in prompt, f"{fact!r} missing from the re-injected prompt"


async def test_a_fact_is_never_dropped_by_a_later_unrelated_turn() -> None:
    """Capturing a symptom on a later turn must not clear the appliance captured earlier
    — accumulation, never replacement."""
    case_file = CaseFile()
    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "dryer"}),
        text="A dryer.",
    )
    await _run(
        case_file,
        ScriptedToolCall("record_symptom", {"description": "no heat"}),
        text="No heat, noted.",
    )
    assert case_file.appliance_type == "dryer"  # still present after the symptom turn
    assert [s.description for s in case_file.symptoms] == ["no heat"]


async def test_correcting_the_appliance_updates_memory_in_place() -> None:
    """The caller correcting themselves (washer → dryer) overwrites the appliance, and
    the stale value must not linger in the re-injected prompt."""
    case_file = CaseFile()
    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "washer"}),
        text="A washer.",
    )
    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "dryer"}),
        text="Oh, a dryer — got it.",
    )
    assert case_file.appliance_type == "dryer"
    prompt = build_system_prompt(case_file)
    assert '"appliance_type":"dryer"' in prompt


# --- Flow / state transitions -------------------------------------------------------


async def test_full_flow_reaches_scheduling_readiness() -> None:
    """greeting → appliance ID → symptom → troubleshooting → identity capture leaves the
    case file holding everything a scheduling handoff needs (zip + appliance_type for
    find_technicians), with the troubleshooting steps recorded along the way."""
    case_file = CaseFile()
    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "washer"}),
        text="A washer.",
    )
    await _run(
        case_file,
        ScriptedToolCall("record_symptom", {"description": "won't spin", "onset": "today"}),
        text="Won't spin.",
    )
    await _run(
        case_file,
        ScriptedToolCall(
            "get_troubleshooting_steps", {"appliance": "washer", "symptom_key": "not_spinning"}
        ),
        text="Let's try a few things.",
    )
    await _run(
        case_file, ScriptedToolCall("update_case_file", {"customer_zip": "60614"}), text="Thanks."
    )

    assert case_file.steps_given, "troubleshooting steps should be recorded"
    # Scheduling-readiness: both inputs find_technicians(zip, appliance_type) needs.
    assert case_file.customer.zip == "60614"
    assert case_file.appliance_type == "washer"


async def test_troubleshooting_steps_land_in_case_file_for_a_valid_key() -> None:
    case_file = CaseFile(appliance_type="oven")
    await _run(
        case_file,
        ScriptedToolCall(
            "get_troubleshooting_steps", {"appliance": "oven", "symptom_key": "not_heating"}
        ),
        text="Here's what to try.",
    )
    assert len(case_file.steps_given) > 0
    assert case_file.safety_flag is False


# --- Illegal jumps are rejected or recovered, never crash the turn ------------------


async def test_invalid_appliance_is_rejected_without_polluting_the_case_file() -> None:
    """An unsupported appliance must leave appliance_type unset (the tool refuses it) and
    the turn must still complete cleanly — a recoverable rejection, not a crash."""
    case_file = CaseFile()
    llm = FakeFunctionCallingLLM(
        script=_tool_then_text(
            ScriptedToolCall("identify_appliance", {"appliance_type": "toaster"}),
            text="Sorry, I don't cover toasters.",
        )
    )
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    events = await _drain(run_turn(case_file, memory, "my toaster is broken", llm=llm))
    assert case_file.appliance_type is None
    assert any(isinstance(e, TurnComplete) for e in events)


async def test_unknown_symptom_key_records_no_steps_and_turn_recovers() -> None:
    """Asking for steps with a symptom_key outside the appliance's vocabulary returns an
    error string; no steps are recorded and the turn completes."""
    case_file = CaseFile(appliance_type="washer")
    llm = FakeFunctionCallingLLM(
        script=_tool_then_text(
            ScriptedToolCall(
                "get_troubleshooting_steps", {"appliance": "washer", "symptom_key": "invented_key"}
            ),
            text="Let me get some more detail.",
        )
    )
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    events = await _drain(run_turn(case_file, memory, "it does a weird thing", llm=llm))
    assert case_file.steps_given == []
    assert case_file.safety_flag is False
    assert any(isinstance(e, TurnComplete) for e in events)


async def test_safety_escalation_locks_out_further_diy_in_the_prompt() -> None:
    """After a safety symptom_key trips the flag, the re-built prompt must instruct the
    model to stop offering DIY steps — the safety interrupt persists structurally, not
    just for the one turn."""
    case_file = CaseFile(appliance_type="oven")
    await _run(
        case_file,
        ScriptedToolCall(
            "get_troubleshooting_steps", {"appliance": "oven", "symptom_key": "safety_gas_smell"}
        ),
        text="Please shut off the gas and step outside.",
    )
    assert case_file.safety_flag is True
    prompt = build_system_prompt(case_file)
    assert "safety escalation has already been triggered" in prompt
    assert "Do not" in prompt and "DIY" in prompt


# --- Booking finalization: accept → book in one step (task #21) ---------------------
# The live bug was model-driven looping (re-searching after an acceptance). These
# hermetic tests pin the loop-level contract the fix depends on: run_turn executes
# exactly the tool calls the model emits, in order, injecting no extra find_technicians.
# (ToolInvoked is emitted before the tool runs, so these hold with no scheduling DB.)


async def test_scripted_acceptance_books_in_a_single_call_without_researching() -> None:
    """When the model responds to an acceptance with one book_appointment call, the loop
    invokes exactly that — no second find_technicians is injected around it."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "book_appointment",
                        {
                            "slot_id": "slot_1",
                            "customer": {"name": "Jordan", "email": "jordan@example.com"},
                            "issue_summary": "dishwasher won't drain",
                        },
                    )
                ]
            ),
            ScriptedTurn(text="You're booked with Alex on Tuesday at 11 AM."),
        ]
    )
    case_file = CaseFile(appliance_type="dishwasher")
    case_file.customer.zip = "60601"
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    events = await _drain(run_turn(case_file, memory, "yes, book the 11 AM slot", llm=llm))

    tool_names = [e.tool_name for e in events if isinstance(e, ToolInvoked)]
    assert tool_names == ["book_appointment"]
    assert "find_technicians" not in tool_names
    assert any(isinstance(e, TurnComplete) for e in events)


async def test_find_technicians_persists_its_zip_into_the_case_file() -> None:
    """Code-level safety net (task #21): find_technicians writes the zip it searches with
    into the case file, so the booking turn still has it even if the model never called
    update_case_file. Durability no longer depends on the model remembering to persist.
    (find_technicians errors with no DB, but the persist happens before the DB call, and
    run_turn swallows the tool error — so the case-file mutation still lands.)"""
    case_file = CaseFile(appliance_type="dishwasher")
    assert case_file.customer.zip is None
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "find_technicians",
                        {"zip": "60601", "appliance_type": "dishwasher"},
                    )
                ]
            ),
            ScriptedTurn(text="Here are a couple of options."),
        ]
    )
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    await _drain(run_turn(case_file, memory, "dishwasher won't drain, I'm at 60601", llm=llm))

    # The zip searched with is now on file — no update_case_file call was scripted.
    assert case_file.customer.zip == "60601"
    assert "60601" in build_system_prompt(case_file)


def test_offered_slots_store_round_trips_by_session() -> None:
    """The session-scoped offered-slots store (task #21): what find_technicians records
    for a session is what run_turn reads back to build that session's next prompt."""
    import uuid

    from app.agent.state import get_offered_slots, set_offered_slots

    sid = uuid.uuid4()
    slots = [{"ref": "slot_1", "technician": "Marcus Bell", "starts_at": "x", "ends_at": "y"}]
    set_offered_slots(sid, slots)
    assert get_offered_slots(sid) == slots
    assert get_offered_slots(uuid.uuid4()) == []  # a different session sees nothing


def test_build_agent_surfaces_stored_offered_slots_in_the_system_prompt() -> None:
    """Wiring proof: the slots stored for a session reach the agent's system prompt via
    build_agent(offered_slots=...), so the acceptance turn's model sees them and can book
    without re-searching. (find_technicians builds these from DB rows, so the write path
    needs a DB; here we drive the store→prompt half that run_turn wires together.)"""
    from app.agent.core import build_agent

    offered = [
        {
            "ref": "slot_1",
            "technician": "Marcus Bell",
            "slot_id": "11111111-1111-1111-1111-111111111111",
            "starts_at": "2026-07-11T15:00:00",
            "ends_at": "2026-07-11T17:00:00",
        }
    ]
    llm = FakeFunctionCallingLLM(script=[ScriptedTurn(text="ok")])
    workflow = build_agent(CaseFile(appliance_type="dishwasher"), llm=llm, offered_slots=offered)
    system_prompt = next(iter(workflow.agents.values())).system_prompt
    assert "slot_1" in system_prompt
    assert "Marcus Bell" in system_prompt
    assert "do NOT call `find_technicians` again" in system_prompt


async def test_find_technicians_zip_overwrites_a_stale_case_file_zip() -> None:
    """Last-spoken wins: searching with a new zip overwrites an earlier one on file
    (correction-in-place), so the case file always reflects the zip actually searched."""
    case_file = CaseFile(appliance_type="dishwasher")
    case_file.customer.zip = "10001"  # an earlier, now-corrected zip
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "find_technicians",
                        {"zip": "60601", "appliance_type": "dishwasher"},
                    )
                ]
            ),
            ScriptedTurn(text="Options for 60601 coming up."),
        ]
    )
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    await _drain(run_turn(case_file, memory, "actually I'm in 60601", llm=llm))

    assert case_file.customer.zip == "60601"


async def test_persisting_zip_alongside_find_technicians_survives_to_next_turn() -> None:
    """The task #21 re-run root cause: a zip passed only as a find_technicians arg is
    gone next turn. This proves the fix mechanism — when the model persists it via
    update_case_file (parallel with find_technicians), it lands in the case file and is
    in the NEXT turn's rebuilt prompt, so the acceptance turn won't re-ask for it.
    (find_technicians has no DB here and errors, but update_case_file still runs; the
    ToolInvoked and the case-file mutation both happen.)"""
    case_file = CaseFile(appliance_type="dishwasher")
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall("update_case_file", {"customer_zip": "60601"}, tool_id="u1"),
                    ScriptedToolCall(
                        "find_technicians",
                        {"zip": "60601", "appliance_type": "dishwasher"},
                        tool_id="f1",
                    ),
                ]
            ),
            ScriptedTurn(text="Here are a couple of options."),
        ]
    )
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    await _drain(run_turn(case_file, memory, "my dishwasher won't drain, I'm in 60601", llm=llm))

    # Zip is now on file (not just a transient tool arg)...
    assert case_file.customer.zip == "60601"
    # ...so the NEXT turn's prompt carries it and the zip precondition is satisfied.
    next_prompt = build_system_prompt(case_file)
    assert "60601" in next_prompt


async def test_propose_then_accept_runs_find_then_book_each_once_in_order() -> None:
    """The full arc across two turns — propose (find_technicians) then accept (book) —
    executes each tool exactly once, in order, with no extra re-search on acceptance."""
    case_file = CaseFile(appliance_type="dishwasher")
    case_file.customer.zip = "60601"
    memory = ChatMemoryBuffer.from_defaults(
        llm=FakeFunctionCallingLLM(script=[ScriptedTurn(text="")])
    )

    # Turn 1: model searches for technicians.
    llm1 = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "find_technicians",
                        {"zip": "60601", "appliance_type": "dishwasher"},
                    )
                ]
            ),
            ScriptedTurn(text="I have Alex Tuesday at 11 AM or Sam Wednesday at 2 PM."),
        ]
    )
    events1 = await _drain(run_turn(case_file, memory, "please schedule someone", llm=llm1))

    # Turn 2: caller accepts → model books, and must NOT search again.
    llm2 = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "book_appointment",
                        {
                            "slot_id": "slot_1",
                            "customer": {"name": "Jordan", "email": "jordan@example.com"},
                            "issue_summary": "dishwasher won't drain",
                        },
                    )
                ]
            ),
            ScriptedTurn(text="Booked — your appointment is confirmed."),
        ]
    )
    events2 = await _drain(run_turn(case_file, memory, "yes, the first one", llm=llm2))

    turn1_tools = [e.tool_name for e in events1 if isinstance(e, ToolInvoked)]
    turn2_tools = [e.tool_name for e in events2 if isinstance(e, ToolInvoked)]
    assert turn1_tools == ["find_technicians"]
    assert turn2_tools == ["book_appointment"]  # accept → book, no re-search
    assert "find_technicians" not in turn2_tools


# --- symptom onset capture (task #43) -----------------------------------------------


async def test_record_symptom_onset_is_carried_into_the_case_file() -> None:
    """The live memory-marathon found every Symptom.onset landing 'unspecified' because
    the model called record_symptom without onset. When it DOES pass onset (which the
    prompt now demands whenever the caller states timing), the value must flow through
    run_turn into the case file — not get dropped."""
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "record_symptom",
                        {"description": "grinding noise", "onset": "last Tuesday"},
                    )
                ]
            ),
            ScriptedTurn(text="Got it — a grinding noise since last Tuesday."),
        ]
    )
    case_file = CaseFile(appliance_type="washer")
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    await _drain(run_turn(case_file, memory, "it's been grinding since last Tuesday", llm=llm))
    assert len(case_file.symptoms) == 1
    assert case_file.symptoms[0].onset == "last Tuesday"


# --- structured diagnostic-fact capture (task #44, generalizes #43) -----------------


async def test_prompt_routes_symptom_details_to_structured_fields() -> None:
    # Task #43/#44 (kept, severed from the reverted #30 contact-persist prose; evals-live
    # bench-proved booking-neutral): a tight rule-3 nudge to put a symptom's timing/
    # error-code/sound in record_symptom's structured params, not the free-text
    # description, and brand/model via update_case_file.
    prompt = build_system_prompt(CaseFile())
    assert "`onset`, `error_code`, and `sound` fields" in prompt
    assert "rather than lumping them into `description`" in prompt
    assert "capture brand and model via `update_case_file`" in prompt


def test_record_symptom_docstring_names_each_structured_param() -> None:
    # Tool-description drift is invisible to the prompt; keep the param purposes crisp so
    # the model routes error_code/sound/onset to their fields, not into description (#44).
    from app.tools.core_tools import record_symptom

    doc = record_symptom.__doc__ or ""
    for param in ("`onset`", "`error_code`", "`sound`", "`description`"):
        assert param in doc, f"record_symptom docstring no longer names {param}"


async def test_all_volunteered_facts_land_in_their_structured_fields_over_a_drip() -> None:
    """Over a drip-fed call, brand/model and a symptom's error_code/sound/onset must each
    land in their OWN structured field — not dropped, and not lumped into the symptom
    description. Proves the capture plumbing through run_turn once the model routes them
    (the live memory-marathon found these intermittently dropped)."""
    case_file = CaseFile()
    await _run(
        case_file,
        ScriptedToolCall("identify_appliance", {"appliance_type": "washer"}),
        ScriptedToolCall("update_case_file", {"brand": "Kenmore", "model": "110.20022311"}),
        text="Got it — a Kenmore washer.",
    )
    await _run(
        case_file,
        ScriptedToolCall(
            "record_symptom",
            {
                "description": "won't spin",
                "error_code": "F21",
                "sound": "grinding",
                "onset": "last Tuesday",
            },
        ),
        text="Noted.",
    )
    assert case_file.appliance_type == "washer"
    assert case_file.brand == "Kenmore"
    assert case_file.model == "110.20022311"
    symptom = case_file.symptoms[0]
    assert symptom.description == "won't spin"
    assert symptom.error_code == "F21"
    assert symptom.sound == "grinding"
    assert symptom.onset == "last Tuesday"


# --- book_appointment contact requirement (task #27) --------------------------------
# A real booking must carry the caller's name + email so the customers row is
# contactable. Enforced only when a case file is bound (a real agent turn); direct
# tool/unit calls (slot-integrity tests) stay inert. The checks below run without a DB:
# the contact guard returns before slot resolution, and a bogus slot id returns before
# any DB call — so a non-contact error proves the contact guard passed.


async def test_book_appointment_requires_name_and_email_on_a_real_booking(monkeypatch) -> None:
    import json

    from app.agent.state import current_case_file
    from app.contracts import Customer
    from app.tools.scheduling_tools import book_appointment

    monkeypatch.delenv("BOOKING_REQUIRE_CONTACT", raising=False)  # default ON
    token = current_case_file.set(CaseFile(appliance_type="washer"))  # bound, empty contact
    try:
        result = json.loads(await book_appointment("slot_1", Customer(), "washer is leaking"))
    finally:
        current_case_file.reset(token)
    assert result["status"] == "error"
    assert "name" in result["message"] and "email" in result["message"]


async def test_book_appointment_passes_contact_gate_when_contact_present(monkeypatch) -> None:
    import json

    from app.agent.state import current_case_file
    from app.contracts import Customer
    from app.tools.scheduling_tools import book_appointment

    monkeypatch.delenv("BOOKING_REQUIRE_CONTACT", raising=False)
    case_file = CaseFile(appliance_type="washer")
    case_file.customer.name = "Jordan"
    case_file.customer.email = "jordan@example.com"
    token = current_case_file.set(case_file)
    try:
        # A bogus slot id → the tool returns a slot-id error AFTER passing the contact
        # gate (and before any DB call), proving contact validation succeeded.
        result = json.loads(await book_appointment("nope", Customer(), "washer is leaking"))
    finally:
        current_case_file.reset(token)
    assert result["status"] == "error"
    assert "not a valid slot id" in result["message"]  # got past the contact gate


async def test_book_appointment_contact_requirement_is_inert_without_a_bound_case_file(
    monkeypatch,
) -> None:
    """The guard that keeps the slot-integrity unit tests (which call book_appointment
    directly, no case file) passing: with no case file bound, contact is not enforced."""
    import json

    from app.contracts import Customer
    from app.tools.scheduling_tools import book_appointment

    monkeypatch.delenv("BOOKING_REQUIRE_CONTACT", raising=False)
    # Name-only customer, no case file bound → no contact error; bogus slot → slot error.
    result = json.loads(await book_appointment("nope", Customer(name="Jamie"), "washer leak"))
    assert result["status"] == "error"
    assert "not a valid slot id" in result["message"]
    assert "Collect the caller" not in result["message"]


async def test_book_appointment_contact_requirement_respects_the_env_flag(monkeypatch) -> None:
    import json

    from app.agent.state import current_case_file
    from app.contracts import Customer
    from app.tools.scheduling_tools import book_appointment

    monkeypatch.setenv("BOOKING_REQUIRE_CONTACT", "0")  # pinned off
    token = current_case_file.set(CaseFile(appliance_type="washer"))  # bound, empty contact
    try:
        result = json.loads(await book_appointment("nope", Customer(), "washer is leaking"))
    finally:
        current_case_file.reset(token)
    # Requirement disabled → no contact error even with an empty case file.
    assert "Collect the caller" not in result["message"]
    assert "not a valid slot id" in result["message"]


async def test_update_case_file_rejects_a_malformed_email_but_keeps_other_fields() -> None:
    """A bad email must not be stored (a wrong address means the upload link never
    arrives), while a valid zip in the same call still lands — partial recovery."""
    case_file = CaseFile()
    await _run(
        case_file,
        ScriptedToolCall(
            "update_case_file",
            {
                "customer_zip": "60614",
                "customer_email": "not-an-email",
            },
        ),
        text="Let me double-check that email.",
    )
    assert case_file.customer.zip == "60614"
    assert case_file.customer.email is None
