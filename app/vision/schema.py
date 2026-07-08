"""Vision analysis output shape (requirements.md §Contract shapes)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisibleIssue(BaseModel):
    issue: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class VisionAnalysis(BaseModel):
    appliance_detected: str | None = None
    brand_guess: str | None = None
    visible_issues: list[VisibleIssue] = Field(default_factory=list)
    matches_reported_symptoms: bool = False
    additional_steps: list[str] = Field(default_factory=list)


VISION_JSON_SCHEMA: dict = {
    "name": "vision_analysis",
    "schema": {
        "type": "object",
        "properties": {
            "appliance_detected": {"type": ["string", "null"]},
            "brand_guess": {"type": ["string", "null"]},
            "visible_issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "evidence": {"type": "string"},
                    },
                    "required": ["issue", "confidence", "evidence"],
                    "additionalProperties": False,
                },
            },
            "matches_reported_symptoms": {"type": "boolean"},
            "additional_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "appliance_detected",
            "brand_guess",
            "visible_issues",
            "matches_reported_symptoms",
            "additional_steps",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}
