"""Scenario schema + loader for the DeepEval / transcript-runner scenario matrix.

Scenario YAML shape (`specs/features/2026-07-08-testing-evals/requirements.md` →
Contract shapes)::

    {id, feature: core|scheduling|visual, requires: [...],
     turns: [{caller: str}, ...],
     assert: {facts: {...}, no_reask: [...], safety_interrupt: bool, booking_row: bool},
     eval: {metrics: [...], rubrics: [...]}}

Two extra fields (not in the frozen contract, additive) mark canaries:

    canary: bool = False        # a deliberate-failure fixture (requirements.md → Decisions #3)
    canary_layer: structural|eval|both = "eval"
    canary_target: str | None   # which metric/rubric this canary is designed to fail

``turns`` only carries the caller's scripted side — the recorded transcript (fixture
or, post-integration, a live agent run) supplies the agent's replies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

Feature = Literal["core", "scheduling", "visual"]
MetricName = Literal["knowledge_retention", "role_adherence", "conversation_completeness"]
RubricName = Literal[
    "safety_interrupt",
    "booking_confirmation",
    "photo_findings",
    "brand_grounding",
    "english_only",
]
CanaryLayer = Literal["structural", "eval", "both"]


class ScenarioTurn(BaseModel):
    caller: str


class ScenarioAssert(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    no_reask: list[str] = Field(default_factory=list)
    safety_interrupt: bool = False
    booking_row: bool = False


class ScenarioEval(BaseModel):
    metrics: list[MetricName] = Field(default_factory=list)
    rubrics: list[RubricName] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    feature: Feature
    requires: list[str] = Field(default_factory=list)
    turns: list[ScenarioTurn]
    assert_: ScenarioAssert = Field(default_factory=ScenarioAssert, alias="assert")
    eval: ScenarioEval = Field(default_factory=ScenarioEval)
    canary: bool = False
    canary_layer: CanaryLayer = "eval"
    canary_target: str | None = None

    @field_validator("turns")
    @classmethod
    def _non_empty_turns(cls, value: list[ScenarioTurn]) -> list[ScenarioTurn]:
        if not value:
            raise ValueError("scenario must script at least one caller turn")
        return value


SCENARIOS_DIR = Path(__file__).parent


def load_scenario_file(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text())
    return Scenario.model_validate(data)


def load_scenarios(root: Path | None = None) -> list[Scenario]:
    """Walk ``root`` (default: this package) for ``*.yaml`` and validate each one.

    Raises on any invalid scenario or duplicate id — this loader IS the validation
    step referenced in plan.md group 2.
    """
    root = root or SCENARIOS_DIR
    scenarios: list[Scenario] = []
    seen_ids: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        scenario = load_scenario_file(path)
        if scenario.id in seen_ids:
            raise ValueError(f"duplicate scenario id {scenario.id!r} in {path}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)
    return scenarios
