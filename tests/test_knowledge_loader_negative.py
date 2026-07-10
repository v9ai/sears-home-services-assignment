"""Knowledge loader negative paths + safety-script content (bugfix-loop T10).

Every schema-rejection test in the existing suite constructs the Pydantic
model directly, so the REAL validation path — file → yaml.safe_load →
`raw or {}` → ApplianceKnowledge — had zero negative coverage: a bad edit to
a shipped YAML that still parses would only fail if it happened to break a
happy-path test. Safety-tree script content was verified for one appliance
(oven) out of six.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from yaml import YAMLError

import app.knowledge.loader as loader
from app.knowledge.loader import (
    ALL_APPLIANCES,
    UnknownApplianceError,
    get_symptom_tree,
    load_knowledge,
)

_SAFETY_ACTION_WORDS = ("turn off", "shut off", "unplug", "leave", "call", "stop", "power")


@pytest.fixture
def knowledge_dir(monkeypatch, tmp_path):
    """Point the loader at a scratch dir and keep the @cache clean both ways."""
    load_knowledge.cache_clear()
    monkeypatch.setattr(loader, "KNOWLEDGE_DIR", tmp_path)
    yield tmp_path
    load_knowledge.cache_clear()


def test_schema_invalid_file_is_rejected_through_the_loader(knowledge_dir) -> None:
    # Valid YAML, invalid knowledge: one tree, no safety tree.
    (knowledge_dir / "washer.yaml").write_text(
        "leaking:\n  questions: []\n  steps: [check the hose]\n  escalate_if: always\n"
    )
    with pytest.raises(ValidationError):
        load_knowledge("washer")


def test_empty_file_resolves_to_empty_dict_and_is_rejected(knowledge_dir) -> None:
    (knowledge_dir / "dryer.yaml").write_text("")
    with pytest.raises(ValidationError):
        load_knowledge("dryer")


def test_broken_yaml_syntax_raises_yaml_error(knowledge_dir) -> None:
    # Pins the current contract: a syntax error propagates as YAMLError rather
    # than returning a partial tree. A future wrap-into-domain-error is a
    # conscious change, not drift.
    (knowledge_dir / "oven.yaml").write_text("symptom: [unclosed\n  steps: -")
    with pytest.raises(YAMLError):
        load_knowledge("oven")


def test_missing_file_raises_unknown_appliance(knowledge_dir) -> None:
    with pytest.raises(UnknownApplianceError):
        load_knowledge("toaster")


def test_get_symptom_tree_unknown_appliance_raises_unknown_appliance() -> None:
    # Previously only the unknown-*symptom* path was covered.
    load_knowledge.cache_clear()
    with pytest.raises(UnknownApplianceError):
        get_symptom_tree("toaster", "anything")


@pytest.mark.parametrize("appliance", ALL_APPLIANCES)
def test_every_safety_tree_carries_an_actionable_script(appliance: str) -> None:
    # Highest-consequence content in the KB: each safety_* tree must escalate
    # and tell the caller to do something protective, for all six appliances —
    # not just the one the original suite spot-checked.
    load_knowledge.cache_clear()
    knowledge = load_knowledge(appliance)
    safety_trees = {k: v for k, v in knowledge.symptoms.items() if k.startswith("safety_")}
    assert safety_trees, f"{appliance} has no safety_ tree"
    for key, tree in safety_trees.items():
        assert tree.steps, f"{appliance}.{key} has no steps"
        assert tree.escalate_if.strip(), f"{appliance}.{key} has an empty escalate_if"
        joined = " ".join(tree.steps).lower()
        assert any(word in joined for word in _SAFETY_ACTION_WORDS), (
            f"{appliance}.{key} steps carry no protective action verb: {tree.steps}"
        )
