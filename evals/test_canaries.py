"""Canary suite: deliberate-failure fixture transcripts that MUST fail their metric.

requirements.md → Decisions #3: "a gate that has never failed proves nothing."
validation.md: "A green canary fails the gate." This file asserts the mirror image of
`test_conversations.py` — each canary's targeted metric(s) must NOT succeed on its
fixture. If one does, that's a harness bug, and this test fails loudly to say so.
"""

from __future__ import annotations

import pytest

from evals.adapter import fixture_to_test_case
from evals.fixture_loader import load_fixture
from evals.gating import missing_requirements
from evals.metrics import build_metrics
from evals.scenarios.schema import Scenario, load_scenarios

_CANARIES: list[Scenario] = [s for s in load_scenarios() if s.canary]


def _scenario_id(scenario: Scenario) -> str:
    return scenario.id


@pytest.mark.parametrize("scenario", _CANARIES, ids=_scenario_id)
def test_canary_fails_its_targeted_metric(scenario: Scenario) -> None:
    missing = missing_requirements(scenario.requires)
    if missing:
        pytest.skip(f"requires unmet: {', '.join(missing)} (sibling feature not merged yet)")

    fixture = load_fixture(scenario.id)
    test_case = fixture_to_test_case(scenario.id, fixture, scenario=scenario)
    metrics = build_metrics(scenario.eval.metrics, scenario.eval.rubrics)
    assert metrics, f"canary {scenario.id!r} declares no metrics/rubrics to prove it can fail"

    still_succeeding = []
    for metric in metrics:
        metric.measure(test_case)
        if metric.is_successful():
            still_succeeding.append(type(metric).__name__)

    assert not still_succeeding, (
        f"canary {scenario.id!r} (target: {scenario.canary_target}) should have failed "
        f"{still_succeeding} but they reported success — a green canary fails the gate."
    )
