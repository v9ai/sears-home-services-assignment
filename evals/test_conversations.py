"""`make eval` — DeepEval conversational gate over the scenario matrix (fixture mode).

COORDINATION.md §4: judged against recorded fixture transcripts, not a live agent;
this module must not import `app.agent`. Every item here is skipped (not failed) by
`evals/conftest.py` when `OPENAI_API_KEY` is absent, and skipped individually when its
scenario's `requires:` aren't met yet (sibling feature not merged).
"""

from __future__ import annotations

import pytest
from deepeval import assert_test

from evals.adapter import fixture_to_test_case
from evals.fixture_loader import load_fixture
from evals.gating import missing_requirements
from evals.metrics import build_metrics
from evals.scenarios.schema import Scenario, load_scenarios

_MATRIX: list[Scenario] = [s for s in load_scenarios() if not s.canary]


def _scenario_id(scenario: Scenario) -> str:
    return scenario.id


@pytest.mark.parametrize("scenario", _MATRIX, ids=_scenario_id)
def test_scenario_meets_eval_gate(scenario: Scenario) -> None:
    missing = missing_requirements(scenario.requires)
    if missing:
        pytest.skip(f"requires unmet: {', '.join(missing)} (sibling feature not merged yet)")

    fixture = load_fixture(scenario.id)
    test_case = fixture_to_test_case(scenario.id, fixture, scenario=scenario)
    metrics = build_metrics(scenario.eval.metrics, scenario.eval.rubrics)
    assert metrics, f"scenario {scenario.id!r} declares no eval metrics/rubrics"
    assert_test(test_case, metrics)
