"""DeepEval adapter unit tests (plan.md group 4) — object construction only, no
metric measurement, so these run with no `OPENAI_API_KEY` needed."""

from __future__ import annotations

from evals.adapter import fixture_to_test_case, transcript_to_turns


def test_transcript_to_turns_maps_agent_role_to_assistant():
    turns = transcript_to_turns(
        [
            {"role": "user", "text": "hi"},
            {"role": "agent", "text": "hello"},
        ]
    )
    assert [t.role for t in turns] == ["user", "assistant"]
    assert [t.content for t in turns] == ["hi", "hello"]


def test_fixture_to_test_case_builds_conversational_test_case():
    fixture = {
        "turns": [{"role": "user", "text": "hi"}, {"role": "agent", "text": "hello"}],
        "case_file": {},
        "flags": {},
    }
    test_case = fixture_to_test_case("demo", fixture)
    assert len(test_case.turns) == 2
    assert test_case.chatbot_role
    assert test_case.scenario == "demo"
