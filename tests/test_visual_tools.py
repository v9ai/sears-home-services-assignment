"""``send_image_upload_link`` / ``check_image_analysis`` agent tools.

Session identity and the case file are threaded via ``app.agent.state``'s per-turn
``ContextVar``s (the same mechanism ``core_tools.py`` uses), so the tests seed those
directly — no Workflow ``Context`` involved (COORDINATION.md §4 stub seam)."""

from __future__ import annotations

import uuid

import pytest

from app.agent.state import current_case_file, current_session_id
from app.contracts import CaseFile
from app.email import backend as email_backend
from app.tools import visual_tools
from app.uploads.store import InMemoryUploadStore, set_store


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


@pytest.fixture
def case_file():
    cf = CaseFile()
    token = current_case_file.set(cf)
    yield cf
    current_case_file.reset(token)


@pytest.fixture
def session_id(case_file):
    sid = uuid.uuid4()
    token = current_session_id.set(sid)
    yield sid
    current_session_id.reset(token)


async def test_send_image_upload_link_no_session_is_graceful(case_file):
    result = await visual_tools.send_image_upload_link("caller@example.com")
    assert "couldn't find an active session" in result


async def test_send_image_upload_link_creates_upload_and_sends_email(upload_store, session_id):
    result = await visual_tools.send_image_upload_link("caller@example.com")
    assert "caller@example.com" in result

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert "http://localhost:3000/upload/" in console.sent[0]["body"]

    assert current_case_file.get().customer.email == "caller@example.com"


async def test_check_image_analysis_no_upload_yet(upload_store, session_id):
    result = await visual_tools.check_image_analysis()
    assert "No photo upload has been requested" in result


async def test_check_image_analysis_progresses_through_statuses(upload_store, session_id):
    record = await upload_store.create(session_id, "caller@example.com")
    pending_result = await visual_tools.check_image_analysis()
    assert "No photo has been uploaded yet" in pending_result

    await upload_store.save_image(record.token, "data/uploads/fake.jpg")
    uploaded_result = await visual_tools.check_image_analysis()
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
    analyzed_result = await visual_tools.check_image_analysis()
    assert "door seal gap" in analyzed_result
    assert "Clean and reseat the door gasket." in analyzed_result

    case_file = current_case_file.get()
    assert case_file.brand == "GE"
    assert case_file.appliance_type == "refrigerator"
    assert "Clean and reseat the door gasket." in case_file.steps_given
