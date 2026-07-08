"""Loader for the deterministic YAML knowledge base (`app/knowledge/<appliance>.yaml`).

No RAG, no embeddings (tech-stack.md forbidden patterns) — a keyed dict lookup loaded
once and cached, exactly as decided in requirements.md Decision 3.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from app.contracts import Appliance
from app.knowledge.schema import ApplianceKnowledge

KNOWLEDGE_DIR = Path(__file__).parent

ALL_APPLIANCES: tuple[Appliance, ...] = (
    "washer",
    "dryer",
    "refrigerator",
    "dishwasher",
    "oven",
    "hvac",
)


class UnknownApplianceError(KeyError):
    pass


class UnknownSymptomKeyError(KeyError):
    pass


@cache
def load_knowledge(appliance: str) -> ApplianceKnowledge:
    """Load and validate one appliance's knowledge file. Cached after first read."""
    path = KNOWLEDGE_DIR / f"{appliance}.yaml"
    if not path.exists():
        raise UnknownApplianceError(appliance)
    raw = yaml.safe_load(path.read_text()) or {}
    return ApplianceKnowledge(appliance=appliance, symptoms=raw)


def load_all_knowledge() -> dict[str, ApplianceKnowledge]:
    """Load every appliance's knowledge file. Used by tests and prompt-building."""
    return {appliance: load_knowledge(appliance) for appliance in ALL_APPLIANCES}


def symptom_keys_for(appliance: str) -> list[str]:
    """The valid ``symptom_key`` vocabulary for one appliance, for prompt injection."""
    return sorted(load_knowledge(appliance).symptoms.keys())


def get_symptom_tree(appliance: str, symptom_key: str):
    knowledge = load_knowledge(appliance)
    tree = knowledge.symptoms.get(symptom_key)
    if tree is None:
        raise UnknownSymptomKeyError(symptom_key)
    return tree
