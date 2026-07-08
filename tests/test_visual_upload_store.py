"""Token lifecycle over the storage-agnostic ``UploadStore`` (InMemory backend) —
validation.md: "Token lifecycle tests: expired token rejected, token single-use..."."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.uploads.store import InMemoryUploadStore, UploadRecord


@pytest.fixture
def store() -> InMemoryUploadStore:
    return InMemoryUploadStore()


async def test_create_returns_pending_record(store: InMemoryUploadStore):
    session_id = uuid.uuid4()
    record = await store.create(session_id, "caller@example.com")
    assert record.status == "pending"
    assert record.session_id == session_id
    assert record.email == "caller@example.com"
    assert record.token


async def test_get_by_token_unknown_returns_none(store: InMemoryUploadStore):
    assert await store.get_by_token("does-not-exist") is None


async def test_expired_token_reads_as_expired(store: InMemoryUploadStore):
    record = await store.create(uuid.uuid4(), "caller@example.com")
    # Force it into the past directly on the in-memory record.
    store._by_token[record.token] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    fetched = await store.get_by_token(record.token)
    assert fetched is not None
    assert fetched.status == "expired"


async def test_single_use_after_image_saved(store: InMemoryUploadStore):
    record = await store.create(uuid.uuid4(), "caller@example.com")
    updated = await store.save_image(record.token, "data/uploads/x.jpg")
    assert updated.status == "uploaded"
    fetched = await store.get_by_token(record.token)
    assert fetched is not None
    assert fetched.status == "uploaded"  # no longer 'pending' -> route rejects re-upload


async def test_save_analysis_transitions_to_analyzed(store: InMemoryUploadStore):
    record = await store.create(uuid.uuid4(), "caller@example.com")
    await store.save_image(record.token, "data/uploads/x.jpg")
    analysis = {"appliance_detected": "washer", "visible_issues": []}
    updated = await store.save_analysis(record.token, analysis)
    assert updated.status == "analyzed"
    assert updated.vision_analysis == analysis


async def test_latest_for_session_picks_most_recent(store: InMemoryUploadStore):
    session_id = uuid.uuid4()
    first = await store.create(session_id, "a@example.com")
    second = UploadRecord(
        session_id=session_id,
        email="b@example.com",
        token="second-token",
        expires_at=first.expires_at,
        created_at=first.created_at + timedelta(seconds=5),
    )
    store._by_token[second.token] = second
    latest = await store.latest_for_session(session_id)
    assert latest is not None
    assert latest.token == second.token


async def test_latest_for_session_none_when_no_uploads(store: InMemoryUploadStore):
    assert await store.latest_for_session(uuid.uuid4()) is None
