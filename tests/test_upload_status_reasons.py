"""GET /api/upload/{token} status projection reasons (bugfix-loop B5).

Before the fix every non-pending, non-expired status collapsed into reason
"already_used" — including "failed", so a caller whose photo analysis died
was told their link had been used. Pin one reason per terminal state.
"""

from __future__ import annotations

import uuid

import pytest

from app.uploads.routes import _status_response
from app.uploads.store import InMemoryUploadStore, set_store


async def _record_with_status(status: str):
    store = InMemoryUploadStore()
    set_store(store)
    record = await store.create(session_id=uuid.uuid4(), email="caller@example.com")
    record.status = status
    return record


async def test_pending_is_valid() -> None:
    resp = _status_response(await _record_with_status("pending"))
    assert resp.valid is True and resp.reason is None


async def test_missing_record_is_not_found() -> None:
    resp = _status_response(None)
    assert resp.valid is False and resp.reason == "not_found"


async def test_expired_reports_expired() -> None:
    resp = _status_response(await _record_with_status("expired"))
    assert resp.valid is False and resp.reason == "expired"


@pytest.mark.parametrize("status", ["uploaded", "analyzed"])
async def test_consumed_link_reports_already_used(status: str) -> None:
    resp = _status_response(await _record_with_status(status))
    assert resp.valid is False and resp.reason == "already_used"


async def test_failed_analysis_reports_failed_not_already_used() -> None:
    # A dead analysis is not a consumed link: the caller (and the upload page)
    # must be able to tell "try again / re-request a link" from "already used".
    resp = _status_response(await _record_with_status("failed"))
    assert resp.valid is False
    assert resp.status == "failed"
    assert resp.reason == "failed"
