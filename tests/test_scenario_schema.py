"""Scenario schema + loader validation (plan.md group 2)."""

from __future__ import annotations

import textwrap

import pytest
import yaml
from pydantic import ValidationError

from evals.scenarios.schema import (
    Scenario,
    load_scenario_file,
    load_scenarios,
)


def _valid_scenario_dict(**overrides):
    data = {
        "id": "unit_scn",
        "feature": "core",
        "turns": [{"caller": "hi"}],
        "assert": {"facts": {}, "no_reask": [], "safety_interrupt": False, "booking_row": False},
        "eval": {"metrics": ["knowledge_retention"], "rubrics": []},
    }
    data.update(overrides)
    return data


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
    # English-only enforcement + the photo_findings / conversation_completeness
    # canaries added by bugfix-loop T7b (every judged gate must be able to fail).
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


# --- Malformed-scenario rejection (a green schema gate must mean something) ----------


def test_valid_scenario_dict_round_trips():
    scenario = Scenario.model_validate(_valid_scenario_dict())
    assert scenario.id == "unit_scn"
    assert scenario.feature == "core"


def test_empty_turns_is_rejected_loudly():
    with pytest.raises(ValidationError, match="at least one caller turn"):
        Scenario.model_validate(_valid_scenario_dict(turns=[]))


def test_missing_id_is_rejected():
    data = _valid_scenario_dict()
    del data["id"]
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_missing_turns_is_rejected():
    data = _valid_scenario_dict()
    del data["turns"]
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_unknown_feature_literal_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(_valid_scenario_dict(feature="hvac_but_not_a_feature"))


def test_turn_missing_caller_field_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(_valid_scenario_dict(turns=[{"speaker": "hi"}]))


def test_unknown_metric_name_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            _valid_scenario_dict(eval={"metrics": ["not_a_metric"], "rubrics": []})
        )


def test_unknown_rubric_name_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            _valid_scenario_dict(eval={"metrics": [], "rubrics": ["not_a_rubric"]})
        )


def test_unknown_canary_layer_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(_valid_scenario_dict(canary=True, canary_layer="sideways"))


def test_wrong_type_for_safety_interrupt_is_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            _valid_scenario_dict(
                **{
                    "assert": {
                        "facts": {},
                        "no_reask": [],
                        "safety_interrupt": "definitely",
                        "booking_row": False,
                    }
                }
            )
        )


def test_assert_and_eval_default_when_omitted():
    data = _valid_scenario_dict()
    del data["assert"]
    del data["eval"]
    scenario = Scenario.model_validate(data)
    assert scenario.assert_.facts == {}
    assert scenario.eval.metrics == []


def test_load_scenario_file_validates_a_written_yaml(tmp_path):
    path = tmp_path / "scn.yaml"
    path.write_text(yaml.safe_dump(_valid_scenario_dict()))
    scenario = load_scenario_file(path)
    assert scenario.id == "unit_scn"


def test_load_scenario_file_raises_on_malformed_yaml_scenario(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        textwrap.dedent("""\
        id: bad_scn
        feature: core
        turns: []
    """)
    )
    with pytest.raises(ValidationError):
        load_scenario_file(path)


def test_load_scenarios_rejects_duplicate_ids(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(yaml.safe_dump(_valid_scenario_dict(id="dup")))
    with pytest.raises(ValueError, match="duplicate scenario id"):
        load_scenarios(root=tmp_path)


def test_load_scenarios_on_empty_root_is_empty(tmp_path):
    assert load_scenarios(root=tmp_path) == []


def test_load_scenarios_surfaces_one_bad_file_among_good_ones(tmp_path):
    (tmp_path / "good.yaml").write_text(yaml.safe_dump(_valid_scenario_dict(id="good")))
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(_valid_scenario_dict(id="bad", turns=[])))
    with pytest.raises(ValidationError):
        load_scenarios(root=tmp_path)
