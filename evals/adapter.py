"""Recorded fixture transcript -> DeepEval `ConversationalTestCase`.

COORDINATION.md §4: fixture mode only. This module must not import `app.agent` — it
adapts whatever `evals/fixture_loader.py` hands it (today: recorded fixtures; after
integration: the lead points the same shape at live-agent-recorded transcripts).
"""

from __future__ import annotations

from typing import Any

from deepeval.test_case import ConversationalTestCase, Turn

CHATBOT_ROLE = (
    "A warm, empathetic Sears Home Services phone/chat service agent. It identifies "
    "the caller's appliance, collects symptoms (what's happening, when it started, "
    "error codes, unusual sounds), gives safe troubleshooting guidance, escalates "
    "immediately and halts troubleshooting on any mention of gas smell, sparking, "
    "burning smell, smoke, or water near electrics, reads back technician/date/time "
    "before confirming any booking, and never re-asks a fact already captured in the "
    "case file."
)

_ROLE_MAP = {"user": "user", "agent": "assistant", "assistant": "assistant"}


def transcript_to_turns(turns: list[dict[str, Any]]) -> list[Turn]:
    mapped: list[Turn] = []
    for turn in turns:
        role = _ROLE_MAP.get(turn["role"], turn["role"])
        mapped.append(Turn(role=role, content=turn["text"]))
    return mapped


def fixture_to_test_case(
    scenario_id: str, fixture: dict[str, Any], scenario: Any | None = None
) -> ConversationalTestCase:
    """Build a `ConversationalTestCase` from a recorded fixture transcript.

    `scenario` (an `evals.scenarios.schema.Scenario`) is optional and only used for
    the `scenario` label deepeval attaches to the test case; the turns themselves
    come entirely from the fixture.
    """
    turns = transcript_to_turns(fixture["turns"])
    return ConversationalTestCase(
        turns=turns,
        chatbot_role=CHATBOT_ROLE,
        scenario=(scenario.id if scenario is not None else scenario_id),
    )
