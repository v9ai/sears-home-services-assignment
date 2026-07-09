"""`make eval-voice` — DeepEval conversational gate over the VOICE channel's spoken output.

Same scenario matrix, metrics, thresholds, and judge as `evals/test_conversations.py`, but
each agent turn is first run through the voice channel's spoken-text sanitizer
(`evals/voice_fixture_lens.voice_lens`) — so this gate proves the Pipecat phone channel's
*spoken* replies still satisfy Knowledge Retention (never-re-ask), Role Adherence (persona),
Conversation Completeness, and the per-feature rubrics. It also re-checks the deterministic
structural assertions on the lensed transcript (sanitization must not disturb the case
file / flags the scenario asserts on).

Skipped (not failed) by `evals/conftest.py` when the judge key is absent, and per-scenario
when a sibling feature's `requires:` aren't met — identical posture to `make eval`.
"""

from __future__ import annotations

import pytest
from deepeval import assert_test

from evals.adapter import fixture_to_test_case
from evals.assertions import check_structural_assertions
from evals.fixture_loader import load_fixture
from evals.gating import missing_requirements
from evals.metrics import build_metrics
from evals.scenarios.schema import Scenario, load_scenarios
from evals.voice_fixture_lens import voice_lens

_MATRIX: list[Scenario] = [s for s in load_scenarios() if not s.canary]


@pytest.mark.parametrize("scenario", _MATRIX, ids=lambda s: s.id)
def test_voice_scenario_meets_eval_gate(scenario: Scenario) -> None:
    missing = missing_requirements(scenario.requires)
    if missing:
        pytest.skip(f"requires unmet: {', '.join(missing)} (sibling feature not merged yet)")

    fixture = voice_lens(load_fixture(scenario.id))

    # Structural parity: the spoken (sanitized) transcript still satisfies the scenario's
    # case-file / safety / booking contract.
    result = check_structural_assertions(scenario, fixture)
    assert result.ok, f"{scenario.id} structural failures after voice lens: {result.failures}"

    # Judged conversational quality on the spoken output.
    test_case = fixture_to_test_case(scenario.id, fixture, scenario=scenario)
    metrics = build_metrics(scenario.eval.metrics, scenario.eval.rubrics)
    assert metrics, f"scenario {scenario.id!r} declares no eval metrics/rubrics"
    assert_test(test_case, metrics)
