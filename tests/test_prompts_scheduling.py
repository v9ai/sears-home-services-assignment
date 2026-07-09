"""Prompt static asserts for the scheduling contract (same pattern as the
latency-engineering acknowledge-before-tools assert): live-run evidence
(2026-07-09, booking-session-attribution manual gate) showed the model calling
`book_appointment` with an invented slot id — the UUIDs from `find_technicians`
must be echoed verbatim, and the prompt is the only place that rule can live
(the frozen tool signature can't carry it)."""

from __future__ import annotations

from app.agent.prompts import SCHEDULING_CONTRACT, build_system_prompt
from app.contracts import CaseFile


def test_scheduling_contract_pins_exact_slot_id_echo():
    assert "exact `slot_id`" in SCHEDULING_CONTRACT
    assert "verbatim" in SCHEDULING_CONTRACT
    # The short-ref escape hatch (2026-07-09-slot-reference-robustness): live models
    # pass ordinals, so the prompt must sanction the `ref` form it will actually use.
    assert "`slot_1`" in SCHEDULING_CONTRACT
    # Recovery path: a lost id means re-fetching, not guessing.
    assert "call `find_technicians` again" in SCHEDULING_CONTRACT


def test_system_prompt_carries_the_scheduling_contract():
    prompt = build_system_prompt(CaseFile())
    assert "exact `slot_id`" in prompt
