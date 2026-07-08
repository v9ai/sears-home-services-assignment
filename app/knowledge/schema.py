"""Pydantic schema for the deterministic YAML diagnostic knowledge base.

Contract shape (requirements.md § Contract shapes):
    {symptom_key: {questions: [str], steps: [str], escalate_if: str}}

Convention (owned by this feature, not a frozen contract): a ``symptom_key`` prefixed
``safety_`` marks the file's mandatory safety-escalation tree — its ``steps`` are the
shutoff/professional-help script, not DIY troubleshooting. This keeps the on-the-wire
shape exactly three keys per entry while giving the loader a deterministic way to find
the safety tree without inventing a fourth field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

SAFETY_KEY_PREFIX = "safety_"


class SymptomTree(BaseModel):
    """One symptom's decision tree: clarifying questions, DIY steps, escalation note."""

    questions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    escalate_if: str


class ApplianceKnowledge(BaseModel):
    """All symptom trees for one appliance, keyed by ``symptom_key``."""

    appliance: str
    symptoms: dict[str, SymptomTree]

    @model_validator(mode="after")
    def _validate_shape(self) -> ApplianceKnowledge:
        if len(self.symptoms) < 3:
            raise ValueError(
                f"{self.appliance}: expected >=3 symptom trees, got {len(self.symptoms)}"
            )
        if not any(key.startswith(SAFETY_KEY_PREFIX) for key in self.symptoms):
            raise ValueError(
                f"{self.appliance}: missing a safety-escalation tree "
                f"(a symptom_key starting with '{SAFETY_KEY_PREFIX}')"
            )
        return self

    def is_safety_key(self, symptom_key: str) -> bool:
        return symptom_key.startswith(SAFETY_KEY_PREFIX)
