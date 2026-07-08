"""Merge vision findings into the session case file.

The ``CaseFile`` contract (frozen, ``app.contracts``) has no dedicated vision-analysis
field, so findings land in the existing fields: ``brand``/``appliance_type`` fill only
if still unset (advisory evidence, never overwrites a caller-stated fact — mission
non-negotiable 2), ``steps_given`` gains the model's ``additional_steps``, and
``safety_flag`` is raised if the visible evidence itself reads as hazardous — the
safety interrupt (mission non-negotiable 1) applies to what the camera sees, not just
what the caller says.
"""

from __future__ import annotations

from typing import get_args

from app.contracts import Appliance, CaseFile
from app.vision.schema import VisionAnalysis

_HAZARD_KEYWORDS = (
    "gas",
    "spark",
    "smoke",
    "burn",
    "fire",
    "water near",
    "exposed wire",
    "electrical",
)

_VALID_APPLIANCES = set(get_args(Appliance))


def _looks_hazardous(analysis: VisionAnalysis) -> bool:
    haystacks = [f"{issue.issue} {issue.evidence}".lower() for issue in analysis.visible_issues]
    return any(keyword in haystack for haystack in haystacks for keyword in _HAZARD_KEYWORDS)


def merge_vision_into_case_file(case_file: CaseFile, analysis: VisionAnalysis) -> CaseFile:
    """Pure merge — no I/O. Returns a new ``CaseFile``; never mutates the input."""
    updates: dict[str, object] = {}

    if case_file.brand is None and analysis.brand_guess:
        updates["brand"] = analysis.brand_guess

    if (
        case_file.appliance_type is None
        and analysis.appliance_detected
        and analysis.appliance_detected in _VALID_APPLIANCES
    ):
        updates["appliance_type"] = analysis.appliance_detected

    if analysis.additional_steps:
        existing = list(case_file.steps_given)
        for step in analysis.additional_steps:
            if step not in existing:
                existing.append(step)
        updates["steps_given"] = existing

    if not case_file.safety_flag and _looks_hazardous(analysis):
        updates["safety_flag"] = True

    if not updates:
        return case_file
    return case_file.model_copy(update=updates)


def summarize_for_agent(analysis: VisionAnalysis) -> str:
    """A natural-language summary handed back as a tool result to the LLM agent."""
    if not analysis.visible_issues:
        lines = ["The photo didn't show any clear visible issues."]
    else:
        lines = ["Visible issues from the photo:"]
        for issue in analysis.visible_issues:
            lines.append(f"- {issue.issue} (confidence {issue.confidence:.0%}): {issue.evidence}")

    if analysis.appliance_detected:
        lines.append(f"Appliance detected: {analysis.appliance_detected}.")
    if analysis.brand_guess:
        lines.append(f"Brand guess: {analysis.brand_guess}.")
    lines.append(
        "This matches what the caller reported."
        if analysis.matches_reported_symptoms
        else "This does not clearly match what the caller reported — probe further."
    )
    if analysis.additional_steps:
        lines.append("Additional steps to consider: " + "; ".join(analysis.additional_steps))
    return "\n".join(lines)
