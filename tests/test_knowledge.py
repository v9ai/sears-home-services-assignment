"""Knowledge loader/schema unit tests (voice-diagnostic-core, validation.md gate 1)."""

from __future__ import annotations

import pytest

from app.knowledge.loader import (
    ALL_APPLIANCES,
    UnknownApplianceError,
    UnknownSymptomKeyError,
    get_symptom_tree,
    load_all_knowledge,
    load_knowledge,
    symptom_keys_for,
)
from app.knowledge.schema import SAFETY_KEY_PREFIX


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
