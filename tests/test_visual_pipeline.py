"""Mocked-vision merge test (validation.md): analysis JSON lands in the case file and
``image_uploads.status`` transitions pending -> uploaded -> analyzed. The OpenAI call
is always avoided here by injecting a canned ``VisionAnalysis`` (COORDINATION.md §4)."""

from __future__ import annotations

import uuid

import pytest

from app.contracts import CaseFile
from app.email import backend as email_backend
from app.uploads.store import InMemoryUploadStore, set_store
from app.vision import pipeline as vision_pipeline
from app.vision.schema import VisibleIssue, VisionAnalysis


def _patch_session(monkeypatch, case_file: CaseFile, *, ended: bool):
    """Pin the pipeline's session load and capture what it persists back, without a DB."""
    captured: dict = {}

    async def _fake_load(_session_id):
        return case_file, ended

    async def _fake_persist(_session_id, merged):
        captured["merged"] = merged

    monkeypatch.setattr(vision_pipeline, "_load_session_case_file", _fake_load)
    monkeypatch.setattr(vision_pipeline, "_persist_session_case_file", _fake_persist)
    return captured


@pytest.fixture
def store():
    s = InMemoryUploadStore()
    set_store(s)
    return s


@pytest.fixture(autouse=True)
def _reset_email(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    email_backend.reset_email_backend()
    yield
    email_backend.reset_email_backend()


async def test_pipeline_transitions_pending_to_uploaded_to_analyzed(store):
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    assert record.status == "pending"

    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")
    assert uploaded.status == "uploaded"

    analysis = VisionAnalysis(
        appliance_detected="washer",
        brand_guess="Kenmore",
        visible_issues=[
            VisibleIssue(issue="frayed hose", confidence=0.6, evidence="visible fraying")
        ],
        additional_steps=["Replace the inlet hose."],
    )
    await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)

    final = await store.get_by_token(record.token)
    assert final is not None
    assert final.status == "analyzed"
    assert final.vision_analysis["appliance_detected"] == "washer"
    assert final.vision_analysis["additional_steps"] == ["Replace the inlet hose."]


async def test_pipeline_falls_back_to_empty_case_file_without_a_live_sessions_table(
    store, monkeypatch
):
    """Standalone/parallel-dev worktrees may not have the `sessions` table
    (0001_core) yet — the pipeline must not crash, per COORDINATION.md §4."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")

    analysis = VisionAnalysis(appliance_detected="dryer")
    result = await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)
    assert result.appliance_detected == "dryer"


async def test_pipeline_emails_findings_when_session_already_ended(store, monkeypatch):
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")

    async def _fake_load(_session_id):
        return CaseFile(), True  # session already ended

    monkeypatch.setattr(vision_pipeline, "_load_session_case_file", _fake_load)

    async def _noop_persist(_session_id, _case_file):
        return None

    monkeypatch.setattr(vision_pipeline, "_persist_session_case_file", _noop_persist)

    analysis = VisionAnalysis(appliance_detected="oven")
    await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert console.sent[0]["to"] == "caller@example.com"
    assert "found" in console.sent[0]["subject"].lower()


async def test_pipeline_does_not_email_while_the_call_is_still_active(store, monkeypatch):
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")
    _patch_session(monkeypatch, CaseFile(), ended=False)

    analysis = VisionAnalysis(appliance_detected="oven")
    await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)

    # Findings are handed to the live agent via check_image_analysis, not emailed mid-call.
    assert email_backend.get_email_backend().sent == []


async def test_pipeline_merge_preserves_caller_fact_and_folds_in_new_evidence(store, monkeypatch):
    """Through the full pipeline: a caller-stated appliance survives, while a still-unknown
    brand and fresh steps from the photo get folded into the persisted case file."""
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")
    captured = _patch_session(monkeypatch, CaseFile(appliance_type="washer"), ended=False)

    analysis = VisionAnalysis(
        appliance_detected="dryer",  # conflicts with the caller — must not win
        brand_guess="Kenmore",
        additional_steps=["Check the drain pump filter."],
    )
    await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)

    merged = captured["merged"]
    assert merged.appliance_type == "washer"  # caller's fact preserved
    assert merged.brand == "Kenmore"  # unknown field filled from vision
    assert "Check the drain pump filter." in merged.steps_given


async def test_pipeline_raises_safety_flag_from_a_hazardous_photo(store, monkeypatch):
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    uploaded = await store.save_image(record.token, "data/uploads/fake.jpg")
    captured = _patch_session(monkeypatch, CaseFile(appliance_type="oven"), ended=False)

    analysis = VisionAnalysis(
        visible_issues=[
            VisibleIssue(issue="charring", confidence=0.9, evidence="burn marks and exposed wire")
        ]
    )
    await vision_pipeline.run_vision_pipeline(uploaded, analysis=analysis)

    assert captured["merged"].safety_flag is True
