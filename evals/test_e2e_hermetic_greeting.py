"""Greeting professionalism / rapport rubric over recorded fixture transcripts.

The frozen `RubricName` Literal in `evals/scenarios/schema.py` (owned by another
feature, read-only here) has no `greeting`/`rapport` entry, so the deliverable's
"greeting professionalism / rapport rubric" cannot be declared via a scenario's
`eval.rubrics:` block. Instead this module applies a bespoke `ConversationalGEval`
to the `core_greeting_*` fixtures directly — the same DeepEval judge and threshold
the built-in rubrics use (`evals/metrics.py`), just an extra criterion the schema
doesn't (yet) enumerate.

Like every item under `evals/`, each test here is skipped (never failed) by
`evals/conftest.py` when the judge provider's API key is absent, and the judge is
constructed lazily inside the test body — never at import — because
`thresholds.judge_model()` resolves the provider key eagerly.
"""

from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.metrics import ConversationalGEval
from deepeval.test_case.conversational_test_case import MultiTurnParams

from evals import thresholds
from evals.adapter import fixture_to_test_case
from evals.fixture_loader import load_fixture
from evals.scenarios.schema import Scenario, load_scenarios

_GREETING_SCENARIOS: list[Scenario] = [
    s for s in load_scenarios() if s.id.startswith("core_greeting_") and not s.canary
]


def _scenario_id(scenario: Scenario) -> str:
    return scenario.id


def _rapport_rubric() -> ConversationalGEval:
    """Bespoke greeting/rapport rubric — built at call time, not import time."""
    return ConversationalGEval(
        name="Greeting Professionalism & Rapport",
        criteria=(
            "Judge the assistant's professionalism and rapport across the call. The "
            "opening turn must be a warm, professional greeting that identifies Sears "
            "Home Services and offers help. Throughout, the assistant must stay "
            "courteous and empathetic — acknowledging a frustrated or anxious caller's "
            "feelings, staying patient with a confused caller, and never being curt, "
            "dismissive, robotic, or condescending. It should use plain, jargon-free "
            "language and keep the caller feeling helped. Penalize heavily a missing or "
            "purely transactional greeting, any rudeness or impatience, or ignoring "
            "clear caller emotion."
        ),
        evaluation_params=[MultiTurnParams.CONTENT, MultiTurnParams.ROLE],
        threshold=thresholds.GEVAL_RUBRIC,
        model=thresholds.judge_model(),
    )


def test_greeting_scenarios_exist() -> None:
    """Guard the id-prefix wiring so a rename can't silently empty this lane."""
    assert _GREETING_SCENARIOS, "no core_greeting_* scenarios found for the rapport rubric"


@pytest.mark.parametrize("scenario", _GREETING_SCENARIOS, ids=_scenario_id)
def test_greeting_meets_rapport_rubric(scenario: Scenario) -> None:
    fixture = load_fixture(scenario.id)
    test_case = fixture_to_test_case(scenario.id, fixture, scenario=scenario)
    assert_test(test_case, [_rapport_rubric()])
