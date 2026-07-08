"""Offline tests for the live scenario driver (`evals/live_driver.py`).

Drives the real agent loop against a scripted `FakeFunctionCallingLLM` (no network,
deterministic) and asserts the driver emits a fixture-shaped dict the structural
assertions accept — i.e. that the live path is a drop-in for a recorded fixture.
"""

from __future__ import annotations

from typing import Any

from evals.assertions import check_structural_assertions
from evals.live_driver import detect_reasks, drive_scenario
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
