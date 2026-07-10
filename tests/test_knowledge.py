"""Knowledge loader/schema unit tests (voice-diagnostic-core, validation.md gate 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.knowledge.loader import (
    ALL_APPLIANCES,
    UnknownApplianceError,
    UnknownSymptomKeyError,
    get_symptom_tree,
    load_all_knowledge,
    load_knowledge,
    symptom_keys_for,
)
from app.knowledge.schema import (
    SAFETY_KEY_PREFIX,
    ApplianceKnowledge,
    SymptomTree,
)


def test_all_six_appliances_load() -> None:
    kb = load_all_knowledge()
    assert set(kb.keys()) == set(ALL_APPLIANCES)


@pytest.mark.parametrize("appliance", ALL_APPLIANCES)
def test_each_appliance_has_at_least_three_symptom_trees(appliance: str) -> None:
    knowledge = load_knowledge(appliance)
    assert len(knowledge.symptoms) >= 3


@pytest.mark.parametrize("appliance", ALL_APPLIANCES)
def test_each_appliance_has_a_safety_escalation_tree(appliance: str) -> None:
    knowledge = load_knowledge(appliance)
    safety_keys = [k for k in knowledge.symptoms if k.startswith(SAFETY_KEY_PREFIX)]
    assert safety_keys, f"{appliance} is missing a {SAFETY_KEY_PREFIX}* tree"
    for key in safety_keys:
        assert knowledge.symptoms[key].steps


@pytest.mark.parametrize("appliance", ALL_APPLIANCES)
def test_every_tree_has_steps_and_escalate_if(appliance: str) -> None:
    knowledge = load_knowledge(appliance)
    for key, tree in knowledge.symptoms.items():
        assert tree.steps, f"{appliance}/{key} has no steps"
        assert tree.escalate_if, f"{appliance}/{key} has no escalate_if"


def test_symptom_keys_for_lists_known_keys() -> None:
    keys = symptom_keys_for("washer")
    assert "safety_water_near_electrics" in keys


def test_get_symptom_tree_returns_expected_tree() -> None:
    tree = get_symptom_tree("oven", "safety_gas_smell")
    assert any("gas" in step.lower() for step in tree.steps)


def test_unknown_appliance_raises() -> None:
    with pytest.raises(UnknownApplianceError):
        load_knowledge("toaster")


def test_unknown_symptom_key_raises() -> None:
    with pytest.raises(UnknownSymptomKeyError):
        get_symptom_tree("washer", "does_not_exist")


# --- Loader caching + vocabulary invariants ----------------------------------------


def test_load_knowledge_is_cached_returns_same_instance() -> None:
    # @cache: repeat loads must not re-parse the YAML — same object identity.
    assert load_knowledge("washer") is load_knowledge("washer")


def test_symptom_keys_for_is_sorted_and_matches_the_loaded_trees() -> None:
    keys = symptom_keys_for("dryer")
    assert keys == sorted(keys)
    assert set(keys) == set(load_knowledge("dryer").symptoms.keys())


def test_is_safety_key_matches_the_prefix_convention() -> None:
    knowledge = load_knowledge("oven")
    for key in knowledge.symptoms:
        assert knowledge.is_safety_key(key) == key.startswith(SAFETY_KEY_PREFIX)


def test_get_symptom_tree_returns_the_same_tree_the_appliance_holds() -> None:
    knowledge = load_knowledge("washer")
    key = next(iter(knowledge.symptoms))
    assert get_symptom_tree("washer", key) is knowledge.symptoms[key]


# --- Schema validation (malformed knowledge rejected loudly) ------------------------


def _tree(**overrides):
    data = {"questions": ["q?"], "steps": ["do a thing"], "escalate_if": "it gets worse"}
    data.update(overrides)
    return data


def test_symptom_tree_requires_at_least_one_step() -> None:
    with pytest.raises(ValidationError):
        SymptomTree(questions=[], steps=[], escalate_if="x")


def test_symptom_tree_requires_escalate_if() -> None:
    with pytest.raises(ValidationError):
        SymptomTree(steps=["a step"])  # escalate_if missing


def test_symptom_tree_questions_default_to_empty() -> None:
    tree = SymptomTree(steps=["a step"], escalate_if="x")
    assert tree.questions == []


def test_appliance_knowledge_rejects_fewer_than_three_trees() -> None:
    with pytest.raises(ValidationError, match="expected >=3 symptom trees"):
        ApplianceKnowledge(
            appliance="washer",
            symptoms={
                "safety_x": _tree(),
                "b": _tree(),
            },
        )


def test_appliance_knowledge_requires_a_safety_tree() -> None:
    with pytest.raises(ValidationError, match="missing a safety-escalation tree"):
        ApplianceKnowledge(
            appliance="washer",
            symptoms={"a": _tree(), "b": _tree(), "c": _tree()},  # no safety_* key
        )


def test_appliance_knowledge_accepts_a_valid_shape() -> None:
    knowledge = ApplianceKnowledge(
        appliance="washer",
        symptoms={"safety_leak": _tree(), "b": _tree(), "c": _tree()},
    )
    assert knowledge.is_safety_key("safety_leak") is True
    assert knowledge.is_safety_key("b") is False
