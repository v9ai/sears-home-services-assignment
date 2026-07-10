"""DeepEval adapter unit tests (plan.md group 4) — object construction only, no
metric measurement, so these run with no `OPENAI_API_KEY` needed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evals.adapter import CHATBOT_ROLE, fixture_to_test_case, transcript_to_turns
from evals.scenarios.schema import Scenario


def test_transcript_to_turns_maps_agent_role_to_assistant():
    turns = transcript_to_turns(
        [
            {"role": "user", "text": "hi"},
            {"role": "agent", "text": "hello"},
        ]
    )
    assert [t.role for t in turns] == ["user", "assistant"]
    assert [t.content for t in turns] == ["hi", "hello"]


def test_transcript_to_turns_passes_assistant_role_through():
    # A live-recorded transcript may already use "assistant"; it must not be re-mapped.
    turns = transcript_to_turns([{"role": "assistant", "text": "hi"}])
    assert turns[0].role == "assistant"


def test_transcript_to_turns_rejects_unmappable_role_loudly():
    # Any role outside user/agent/assistant is passed through raw and rejected by the
    # deepeval Turn model — a malformed transcript must fail, not silently coerce.
    with pytest.raises(ValidationError):
        transcript_to_turns([{"role": "system", "text": "hi"}])


def test_fixture_to_test_case_builds_conversational_test_case():
    fixture = {
        "turns": [{"role": "user", "text": "hi"}, {"role": "agent", "text": "hello"}],
        "case_file": {},
        "flags": {},
    }
    test_case = fixture_to_test_case("demo", fixture)
    assert len(test_case.turns) == 2
    assert test_case.chatbot_role == CHATBOT_ROLE
    assert test_case.scenario == "demo"


def test_fixture_to_test_case_prefers_scenario_object_id_over_arg():
    scenario = Scenario.model_validate(
        {"id": "real_id", "feature": "core", "turns": [{"caller": "hi"}]}
    )
    fixture = {"turns": [{"role": "user", "text": "hi"}], "case_file": {}, "flags": {}}
    test_case = fixture_to_test_case("passed_in_label", fixture, scenario=scenario)
    assert test_case.scenario == "real_id"


def test_fixture_to_test_case_preserves_turn_order_and_content():
    fixture = {
        "turns": [
            {"role": "agent", "text": "greeting"},
            {"role": "user", "text": "my washer broke"},
            {"role": "agent", "text": "sorry to hear that"},
        ],
        "case_file": {},
        "flags": {},
    }
    test_case = fixture_to_test_case("demo", fixture)
    assert [t.role for t in test_case.turns] == ["assistant", "user", "assistant"]
    assert test_case.turns[1].content == "my washer broke"
