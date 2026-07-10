"""``send_image_upload_link`` / ``check_image_analysis`` agent tools.

Session identity and the case file are threaded via ``app.agent.state``'s per-turn
``ContextVar``s (the same mechanism ``core_tools.py`` uses), so the tests seed those
directly — no Workflow ``Context`` involved (COORDINATION.md §4 stub seam)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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


async def test_send_image_upload_link_rejects_invalid_email(upload_store, session_id):
    result = await visual_tools.send_image_upload_link("not an email")
    assert "doesn't look like a valid email" in result

    console = email_backend.get_email_backend()
    assert console.sent == []
    assert await upload_store.latest_for_session(session_id) is None
    assert current_case_file.get().customer.email is None


async def test_send_image_upload_link_normalizes_spoken_email(upload_store, session_id):
    result = await visual_tools.send_image_upload_link("D dot Martinez99 at Gmail dot com.")
    assert "d.martinez99@gmail.com" in result

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert console.sent[0]["to"] == "d.martinez99@gmail.com"
    assert current_case_file.get().customer.email == "d.martinez99@gmail.com"

    record = await upload_store.latest_for_session(session_id)
    assert record is not None and record.email == "d.martinez99@gmail.com"


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


async def test_check_image_analysis_reports_expired_link(upload_store, session_id):
    record = await upload_store.create(session_id, "caller@example.com")
    upload_store._by_token[record.token] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    result = await visual_tools.check_image_analysis()
    assert "expired" in result.lower()


async def test_check_image_analysis_no_active_session_is_graceful():
    # No current_session_id set → the tool degrades instead of raising.
    result = await visual_tools.check_image_analysis()
    assert "No active session" in result


async def test_check_image_analysis_does_not_clobber_caller_stated_appliance(
    upload_store, session_id
):
    """Enhanced-troubleshooting conflict case: the caller said 'washer', the photo reads
    'dryer'. Folding the analysis into the live case file must keep the caller's appliance
    so subsequent diagnostic guidance stays on the caller-stated path."""
    case_file = current_case_file.get()
    case_file.appliance_type = "washer"

    record = await upload_store.create(session_id, "caller@example.com")
    await upload_store.save_image(record.token, "data/uploads/fake.jpg")
    await upload_store.save_analysis(
        record.token,
        {
            "appliance_detected": "dryer",
            "brand_guess": "Kenmore",
            "visible_issues": [],
            "matches_reported_symptoms": False,
            "additional_steps": [],
        },
    )
    result = await visual_tools.check_image_analysis()

    assert current_case_file.get().appliance_type == "washer"  # never clobbered
    assert current_case_file.get().brand == "Kenmore"  # unknown field still filled
    assert "does not clearly match" in result  # summary tells the agent to probe further


async def test_check_image_analysis_hazard_photo_raises_live_safety_flag(upload_store, session_id):
    """A hazardous photo folds a safety_flag onto the live case file — the structural
    signal that flips the agent's next turn onto the safety-escalation path."""
    case_file = current_case_file.get()
    assert case_file.safety_flag is False

    record = await upload_store.create(session_id, "caller@example.com")
    await upload_store.save_image(record.token, "data/uploads/fake.jpg")
    await upload_store.save_analysis(
        record.token,
        {
            "appliance_detected": "oven",
            "brand_guess": None,
            "visible_issues": [
                {"issue": "charring", "confidence": 0.9, "evidence": "burn marks, exposed wire"}
            ],
            "matches_reported_symptoms": True,
            "additional_steps": [],
        },
    )
    await visual_tools.check_image_analysis()

    assert current_case_file.get().safety_flag is True


async def test_send_link_reuses_case_file_email_without_overwriting_a_different_one(
    upload_store, session_id
):
    """If the caller confirms a fresh address, the case file's email is updated to match
    the address the link was actually sent to."""
    case_file = current_case_file.get()
    case_file.customer.email = "old@example.com"

    await visual_tools.send_image_upload_link("new@example.com")
    assert current_case_file.get().customer.email == "new@example.com"

    record = await upload_store.latest_for_session(session_id)
    assert record is not None and record.email == "new@example.com"
