"""Scenario schema + loader validation (plan.md group 2)."""

from __future__ import annotations

from evals.scenarios.schema import Scenario, load_scenarios


def test_load_scenarios_matrix_is_valid_and_unique():
    scenarios = load_scenarios()
    # ~24-scenario matrix (requirements.md: 18 core + 4 scheduling + 2 visual) + the
    # 4 mandatory failure canaries (plan.md group 5).
    assert len(scenarios) >= 24 + 4
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))
    for scenario in scenarios:
        assert isinstance(scenario, Scenario)
        assert scenario.turns


def test_matrix_covers_core_scheduling_visual():
    scenarios = load_scenarios()
    features = {s.feature for s in scenarios}
    assert features == {"core", "scheduling", "visual"}


def test_core_matrix_has_happy_safety_error_code_per_appliance():
    scenarios = {s.id for s in load_scenarios() if s.feature == "core" and not s.canary}
    appliances = ["washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac"]
    for appliance in appliances:
        for variant in ("happy", "safety", "error_code"):
            assert f"core_{appliance}_{variant}" in scenarios


def test_scheduling_and_visual_scenarios_are_requires_gated():
    scenarios = load_scenarios()
    for scenario in scenarios:
        if scenario.feature == "scheduling":
            assert "scheduling" in scenario.requires
        if scenario.feature == "visual":
            assert "visual" in scenario.requires


def test_every_scenario_declares_eval_coverage():
    for scenario in load_scenarios():
        assert scenario.eval.metrics or scenario.eval.rubrics, (
            f"{scenario.id} declares no eval metrics/rubrics"
        )


def test_canaries_present_and_cover_all_required_metrics():
    canaries = [s for s in load_scenarios() if s.canary]
    # 4 mandatory failure canaries (plan.md group 5) + the brand_grounding canary
    # added with the library brand guides + the english_only canary added with the
    # English-only enforcement.
    assert len(canaries) == 8
    covered = set()
    for canary in canaries:
        covered.update(canary.eval.metrics)
        covered.update(canary.eval.rubrics)
    assert covered == {
        "knowledge_retention",
        "role_adherence",
        "safety_interrupt",
        "booking_confirmation",
        "brand_grounding",
        "english_only",
        "photo_findings",
        "conversation_completeness",
    }
