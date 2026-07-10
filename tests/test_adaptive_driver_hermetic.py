"""Hermetic drive of the adaptive-loop body (bugfix-loop T7, first half).

`drive_adaptive`'s loop — the convergence machinery, turn budget, and the
channel-fidelity safety short-circuit — previously executed only under
`-m live` with real keys; the safety short-circuit was "tested" by grepping
the driver's source for the guard call, which cannot catch a logic regression
(flag set but agent still invoked, wrong ordering). These tests drive the real
loop against `FakeFunctionCallingLLM` and assert behavior, not source text.
"""

from __future__ import annotations

from app.agent.safety import SAFETY_RESPONSE
from evals.adaptive_driver import AdaptiveScenario, drive_adaptive
from tests.fakes import FakeFunctionCallingLLM, ScriptedTurn


def _scenario(**overrides) -> AdaptiveScenario:
    base = dict(
        id="hermetic",
        appliance="oven",
        symptom="smells odd when it runs",
        zip="60601",
        upfront=False,
    )
    return AdaptiveScenario(**{**base, **overrides})


async def test_safety_short_circuit_skips_the_agent_and_sets_the_flag() -> None:
    # Turn 1: benign opener → scripted agent question. Turn 2: the policy
    # injects the hazard line → the driver must answer with SAFETY_RESPONSE
    # WITHOUT consuming a scripted LLM turn. Turn 3: policy accepts the safety
    # response's scheduling offer → scripted terminal confirmation.
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(text="Sorry to hear that — could you tell me more about it?"),
            ScriptedTurn(text="You're all set — your appointment is booked for tomorrow."),
        ]
    )
    scenario = _scenario(safety_line="I smell gas near the oven")
    drive = await drive_adaptive(scenario, llm=llm)

    assert drive["safety_flag"] is True
    agent_texts = [t["text"] for t in drive["turns"] if t["role"] == "agent"]
    assert SAFETY_RESPONSE in agent_texts
    # The behavioral core of the guarantee: the hazard turn consumed NO
    # scripted LLM turn — the agent was skipped, not merely flagged.
    assert llm._call_index == 2
    assert drive["turns_used"] == 3
    assert drive["converged"] is True


async def test_converges_on_a_booking_terminal_reply() -> None:
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(
                text="Great news — your appointment is confirmed for tomorrow at 8. You're all set!"
            )
        ]
    )
    drive = await drive_adaptive(_scenario(upfront=True), llm=llm)
    assert drive["converged"] is True
    assert drive["turns_used"] == 1
    assert drive["nudges"] == 0


async def test_turn_budget_bounds_a_divergent_agent() -> None:
    # Non-terminal, non-question replies force the policy's generic nudge
    # every turn; the loop must stop at max_turns and report non-convergence.
    llm = FakeFunctionCallingLLM(
        script=[ScriptedTurn(text="Let me look into that for a moment.")] * 3
    )
    drive = await drive_adaptive(_scenario(max_turns=3), llm=llm)
    assert drive["converged"] is False
    assert drive["turns_used"] == 3
    assert drive["nudges"] == 3


async def test_reask_after_stated_fact_is_flagged_through_the_drive() -> None:
    # Upfront opener states the zip; the scripted agent asks for it again
    # (mentions the field, interrogative, does not echo the value) → the drive
    # must surface the re-ask via detect_reasks_ordered wiring.
    llm = FakeFunctionCallingLLM(
        script=[
            ScriptedTurn(text="Thanks! What is your zip code?"),
            ScriptedTurn(text="Perfect — your appointment is booked for tomorrow."),
        ]
    )
    drive = await drive_adaptive(_scenario(upfront=True), llm=llm)
    assert "customer.zip" in drive["reasked_fields"]
    assert drive["converged"] is True
