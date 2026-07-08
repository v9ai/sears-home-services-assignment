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
