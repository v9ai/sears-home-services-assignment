"""Vision-analysis merge into the case file — pure logic, no I/O, no OpenAI call."""

from __future__ import annotations

from app.contracts import CaseFile, Symptom
from app.vision.merge import merge_vision_into_case_file, summarize_for_agent
from app.vision.schema import VisibleIssue, VisionAnalysis


def test_merge_fills_unset_brand_and_appliance():
    case_file = CaseFile()
    analysis = VisionAnalysis(appliance_detected="washer", brand_guess="Kenmore")
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.appliance_type == "washer"
    assert merged.brand == "Kenmore"
    assert case_file.brand is None  # input untouched


def test_merge_never_overwrites_a_caller_stated_fact():
    case_file = CaseFile(appliance_type="dryer", brand="Whirlpool")
    analysis = VisionAnalysis(appliance_detected="washer", brand_guess="Kenmore")
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.appliance_type == "dryer"
    assert merged.brand == "Whirlpool"


def test_merge_ignores_invalid_appliance_label():
    case_file = CaseFile()
    analysis = VisionAnalysis(appliance_detected="toaster")  # not one of the six
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.appliance_type is None


def test_merge_appends_additional_steps_deduped():
    case_file = CaseFile(steps_given=["Unplug and reset."])
    analysis = VisionAnalysis(additional_steps=["Unplug and reset.", "Check the drain hose."])
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.steps_given == ["Unplug and reset.", "Check the drain hose."]


def test_merge_raises_safety_flag_on_hazard_evidence():
    case_file = CaseFile()
    analysis = VisionAnalysis(
        visible_issues=[
            VisibleIssue(issue="scorch mark", confidence=0.9, evidence="burn marks near the outlet")
        ]
    )
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.safety_flag is True


def test_merge_leaves_safety_flag_alone_when_no_hazard():
    case_file = CaseFile(symptoms=[Symptom(description="won't spin", onset="yesterday")])
    analysis = VisionAnalysis(
        visible_issues=[VisibleIssue(issue="worn belt", confidence=0.5, evidence="frayed belt")]
    )
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged.safety_flag is False


def test_merge_is_a_noop_when_analysis_adds_nothing():
    case_file = CaseFile(appliance_type="oven", brand="GE", steps_given=["Check the igniter."])
    analysis = VisionAnalysis()
    merged = merge_vision_into_case_file(case_file, analysis)
    assert merged == case_file


def test_summarize_for_agent_mentions_confidence_and_steps():
    analysis = VisionAnalysis(
        appliance_detected="dishwasher",
        visible_issues=[
            VisibleIssue(issue="leaking gasket", confidence=0.75, evidence="water pooling")
        ],
        matches_reported_symptoms=False,
        additional_steps=["Inspect the door seal."],
    )
    summary = summarize_for_agent(analysis)
    assert "leaking gasket" in summary
    assert "75%" in summary
    assert "does not clearly match" in summary
    assert "Inspect the door seal." in summary
