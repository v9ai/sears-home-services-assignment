"""Offline tests for the live scenario driver (`evals/live_driver.py`).

Drives the real agent loop against a scripted `FakeFunctionCallingLLM` (no network,
deterministic) and asserts the driver emits a fixture-shaped dict the structural
assertions accept — i.e. that the live path is a drop-in for a recorded fixture.
"""

from __future__ import annotations

from typing import Any

from evals.assertions import check_structural_assertions
from evals.live_driver import appointments_booking_probe, detect_reasks, drive_scenario
from evals.scenarios.schema import Scenario
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


def _scenario(scenario_id: str, turns: list[str], assert_block: dict[str, Any]) -> Scenario:
    return Scenario.model_validate(
        {
            "id": scenario_id,
            "feature": "core",
            "turns": [{"caller": t} for t in turns],
            "assert": assert_block,
        }
    )


async def test_drive_scenario_emits_fixture_shaped_transcript_that_passes_assertions() -> None:
    scenario = _scenario(
        "live_core_smoke",
        ["My washer won't drain.", "My zip is 60614."],
        {
            "facts": {"appliance_type": "washer", "customer.zip": "60614"},
            "no_reask": [],
            "safety_interrupt": False,
            "booking_row": False,
        },
    )
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("identify_appliance", {"appliance_type": "washer"})]
            ),
            ScriptedTurn(text="Got it — a washer that won't drain."),
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("update_case_file", {"customer_zip": "60614"})]
            ),
            ScriptedTurn(text="Thanks, I've noted zip 60614."),
        ]
    )

    fixture = await drive_scenario(scenario, llm=llm)

    # Shape: leading agent greeting, then strict user/agent alternation.
    assert fixture["turns"][0]["role"] == "agent"
    roles = [t["role"] for t in fixture["turns"]]
    assert roles == ["agent", "user", "agent", "user", "agent"]
    assert fixture["case_file"]["appliance_type"] == "washer"
    assert fixture["case_file"]["customer"]["zip"] == "60614"
    assert fixture["flags"] == {
        "safety_interrupt": False,
        "booking_row": False,
        "reasked_fields": [],
    }
    # The whole point: the driver's output is a drop-in for a recorded fixture.
    assert check_structural_assertions(scenario, fixture).ok


async def test_drive_scenario_captures_safety_interrupt() -> None:
    scenario = _scenario(
        "live_safety_smoke",
        ["I smell gas near my oven.", "What should I do?"],
        {"facts": {}, "safety_interrupt": True, "booking_row": False},
    )
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("identify_appliance", {"appliance_type": "oven"})]
            ),
            ScriptedTurn(text="That's a safety issue."),
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "get_troubleshooting_steps",
                        {"appliance": "oven", "symptom_key": "safety_gas_smell"},
                    )
                ]
            ),
            ScriptedTurn(text="Please shut off the gas and leave the home."),
        ]
    )

    fixture = await drive_scenario(scenario, llm=llm)

    assert fixture["case_file"]["safety_flag"] is True
    assert fixture["flags"]["safety_interrupt"] is True
    assert check_structural_assertions(scenario, fixture).ok


async def test_drive_scenario_uses_injected_booking_probe() -> None:
    scenario = _scenario(
        "live_booking_probe",
        ["My dryer is broken, please book someone."],
        {"facts": {"appliance_type": "dryer"}, "booking_row": True},
    )
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("identify_appliance", {"appliance_type": "dryer"})]
            ),
            ScriptedTurn(text="Booked."),
        ]
    )

    async def probe(_session_id: Any) -> bool:
        return True

    fixture = await drive_scenario(scenario, llm=llm, booking_probe=probe)

    assert fixture["flags"]["booking_row"] is True
    assert check_structural_assertions(scenario, fixture).ok


async def test_drive_scenario_collects_trace_when_requested(monkeypatch) -> None:
    async def _fake_synthesize(text, **kwargs):
        yield b"\x00\x00"

    monkeypatch.setattr("app.agent.tts.synthesize", _fake_synthesize)

    scenario = _scenario(
        "live_trace_smoke",
        ["My washer won't drain."],
        {"facts": {"appliance_type": "washer"}},
    )
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("identify_appliance", {"appliance_type": "washer"})]
            ),
            ScriptedTurn(text="Got it — a washer that won't drain."),
        ]
    )

    fixture = await drive_scenario(scenario, llm=llm, collect_latency=True)

    assert len(fixture["trace"]) == 1
    record = fixture["trace"][0]
    assert record["channel"] == "web"
    assert record["turn_total_ms"] is not None


async def test_drive_scenario_trace_empty_by_default() -> None:
    scenario = _scenario("live_trace_off", ["My washer won't drain."], {"facts": {}})
    llm = FakeFunctionCallingLLM(script=[ScriptedTurn(text="Okay.")])

    fixture = await drive_scenario(scenario, llm=llm)

    assert fixture["trace"] == []
    # Regression guard: every existing assertion in this file still holds unaffected.
    assert fixture["flags"] == {
        "safety_interrupt": False,
        "booking_row": False,
        "reasked_fields": [],
    }


def test_detect_reasks_flags_repeated_question_for_known_field() -> None:
    scenario = _scenario("x", ["a"], {"no_reask": ["customer.zip"]})
    reasked = detect_reasks(
        ["What's your zip code again?"], {"customer": {"zip": "60614"}}, scenario
    )
    assert reasked == ["customer.zip"]


def test_detect_reasks_ignores_mere_reference_to_captured_field() -> None:
    scenario = _scenario("x", ["a"], {"no_reask": ["customer.zip"]})
    reasked = detect_reasks(
        ["I have your zip as 60614, so I'll search there."],
        {"customer": {"zip": "60614"}},
        scenario,
    )
    assert reasked == []


def test_detect_reasks_skips_field_not_yet_captured() -> None:
    # No re-ask is possible for a field the case file never captured — asking for it is
    # the *first* ask, not a re-ask.
    scenario = _scenario("x", ["a"], {"no_reask": ["customer.zip"]})
    reasked = detect_reasks(["What's your zip code?"], {"customer": {}}, scenario)
    assert reasked == []


def test_detect_reasks_skips_field_with_no_registered_keywords() -> None:
    # A no_reask field the heuristic has no keywords for is left alone (best-effort only).
    scenario = _scenario("x", ["a"], {"no_reask": ["symptoms.0.error_code"]})
    reasked = detect_reasks(
        ["What was that error code again?"],
        {"symptoms": [{"error_code": "5E"}]},
        scenario,
    )
    assert reasked == []


def test_detect_reasks_needs_both_keyword_and_a_question_marker() -> None:
    # A captured field mentioned without any interrogative marker is not a re-ask.
    scenario = _scenario("x", ["a"], {"no_reask": ["brand"]})
    reasked = detect_reasks(["Your LG brand unit is a common one."], {"brand": "LG"}, scenario)
    assert reasked == []


async def test_default_booking_inference_from_tool_invocation() -> None:
    # With no probe injected, booking_row is inferred from whether book_appointment ran.
    scenario = _scenario(
        "live_default_booking",
        ["Book a tech for my dryer."],
        {"facts": {}, "booking_row": True},
    )
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall("book_appointment", {"technician_id": "t1", "slot": "9am"})
                ]
            ),
            ScriptedTurn(text="Booked."),
        ]
    )
    fixture = await drive_scenario(scenario, llm=llm)
    assert fixture["flags"]["booking_row"] is True


async def test_default_booking_inference_false_without_the_tool() -> None:
    scenario = _scenario("live_no_booking", ["Just a question."], {"facts": {}})
    llm = FakeFunctionCallingLLM(script=[ScriptedTurn(text="Sure, ask away.")])
    fixture = await drive_scenario(scenario, llm=llm)
    assert fixture["flags"]["booking_row"] is False


async def test_appointments_booking_probe_is_false_for_none_session_without_db() -> None:
    # The ready-made probe short-circuits on a None session id BEFORE importing any DB
    # code, so it's safe to exercise hermetically (no Postgres, no SQLAlchemy import).
    probe = appointments_booking_probe()
    assert await probe(None) is False


async def test_trace_first_audio_overlaps_the_turn(monkeypatch) -> None:
    """Regression (runbook §1 bench-fidelity RCA item 2): the driver must start
    first-sentence TTS while the turn is still streaming — the pre-fix driver drained
    the whole turn first, so submit_to_first_audio exceeded turn_total in EVERY record."""

    async def _fake_synthesize(text, **kwargs):
        yield b"\x00\x00"

    monkeypatch.setattr("app.agent.tts.synthesize", _fake_synthesize)

    scenario = _scenario("live_trace_overlap", ["My washer won't drain."], {"facts": {}})
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                text=(
                    "Got it, that sounds frustrating and we can definitely look into it. "
                    "Let's check the drain hose, the filter, and the pump for any clogs "
                    "before we consider booking a technician visit for your washer."
                )
            ),
        ]
    )

    fixture = await drive_scenario(scenario, llm=llm, collect_latency=True)

    record = fixture["trace"][0]
    assert record["submit_to_first_audio_ms"] is not None
    assert record["submit_to_first_audio_ms"] <= record["turn_total_ms"]
