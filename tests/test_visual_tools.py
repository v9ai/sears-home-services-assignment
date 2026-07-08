"""``send_image_upload_link`` / ``check_image_analysis`` agent tools.

Uses a duck-typed fake in place of ``llama_index.core.workflow.Context`` — the tools
only ever call ``ctx.store.get``/``ctx.store.set``, so a real running Workflow isn't
needed to exercise them (COORDINATION.md §4 stub seam)."""

from __future__ import annotations

import uuid

import pytest

from app.email import backend as email_backend
from app.tools import visual_tools
from app.uploads.store import InMemoryUploadStore, set_store


class FakeStore:
    def __init__(self):
        self._data: dict[str, object] = {}

    async def get(self, path: str, default=None):
        return self._data.get(path, default)

    async def set(self, path: str, value) -> None:
        self._data[path] = value


class FakeContext:
    def __init__(self):
        self.store = FakeStore()

    async def seed(self, session_id: uuid.UUID) -> None:
        await self.store.set(visual_tools.SESSION_ID_KEY, str(session_id))


@pytest.fixture
def upload_store():
    s = InMemoryUploadStore()
    set_store(s)
    return s


@pytest.fixture(autouse=True)
def _console_email(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:3000")
    email_backend.reset_email_backend()
    yield
    email_backend.reset_email_backend()


async def _ctx_with_session() -> FakeContext:
    ctx = FakeContext()
    await ctx.seed(uuid.uuid4())
    return ctx


async def test_send_image_upload_link_no_session_is_graceful():
    ctx = FakeContext()
    result = await visual_tools.send_image_upload_link(ctx, "caller@example.com")
    assert "couldn't find an active session" in result


async def test_send_image_upload_link_creates_upload_and_sends_email(upload_store):
    ctx = await _ctx_with_session()
    result = await visual_tools.send_image_upload_link(ctx, "caller@example.com")
    assert "caller@example.com" in result

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert "http://localhost:3000/upload/" in console.sent[0]["body"]

    case_file = await visual_tools._get_case_file(ctx)
    assert case_file.customer.email == "caller@example.com"


async def test_check_image_analysis_no_upload_yet():
    ctx = await _ctx_with_session()
    result = await visual_tools.check_image_analysis(ctx)
    assert "No photo upload has been requested" in result


async def test_check_image_analysis_progresses_through_statuses(upload_store):
    ctx = await _ctx_with_session()
    session_id = await visual_tools._get_session_id(ctx)

    record = await upload_store.create(session_id, "caller@example.com")
    pending_result = await visual_tools.check_image_analysis(ctx)
    assert "No photo has been uploaded yet" in pending_result

    await upload_store.save_image(record.token, "data/uploads/fake.jpg")
    uploaded_result = await visual_tools.check_image_analysis(ctx)
    assert "still being analyzed" in uploaded_result

    analysis = {
        "appliance_detected": "refrigerator",
        "brand_guess": "GE",
        "visible_issues": [
            {"issue": "door seal gap", "confidence": 0.7, "evidence": "visible gap in gasket"}
        ],
        "matches_reported_symptoms": True,
        "additional_steps": ["Clean and reseat the door gasket."],
    }
    await upload_store.save_analysis(record.token, analysis)
    analyzed_result = await visual_tools.check_image_analysis(ctx)
    assert "door seal gap" in analyzed_result
    assert "Clean and reseat the door gasket." in analyzed_result

    case_file = await visual_tools._get_case_file(ctx)
    assert case_file.brand == "GE"
    assert case_file.appliance_type == "refrigerator"
    assert "Clean and reseat the door gasket." in case_file.steps_given
