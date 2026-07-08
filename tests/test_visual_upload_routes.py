"""HTTP-level upload route tests — oversize/bad-mime/expiry/single-use rejections
(validation.md automated gate). Builds a standalone FastAPI app around just the
upload router (app.main doesn't mount it yet — see plan.md § Integration deltas),
per COORDINATION.md §4 ("routes ... run standalone; fake a session row")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.uploads import routes as upload_routes
from app.uploads.store import InMemoryUploadStore, set_store

JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 100  # not a real jpeg, content-type is what's checked


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = InMemoryUploadStore()
    set_store(store)
    monkeypatch.setattr(upload_routes, "UPLOAD_DIR", str(tmp_path))
    # Don't hit OpenAI from the background task in route tests.
    monkeypatch.setattr(upload_routes, "_analyze_in_background", _noop_async)

    app = FastAPI()
    app.include_router(upload_routes.router)
    with TestClient(app) as test_client:
        yield test_client, store


async def _noop_async(token: str) -> None:
    return None


def test_upload_success(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "uploaded"


def test_upload_unknown_token_404(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/upload/nonexistent",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 404


def test_upload_expired_token_410(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    store._by_token[record.token] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 410


def test_upload_single_use_409(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    first = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert first.status_code == 200
    second = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert second.status_code == 409


def test_upload_disallowed_mime_415(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.gif", b"GIF89a", "image/gif")},
    )
    assert resp.status_code == 415


def test_upload_oversize_413(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    too_big = b"0" * (10 * 1024 * 1024 + 1)
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", too_big, "image/jpeg")},
    )
    assert resp.status_code == 413


def test_status_endpoint_reports_validity(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    resp = test_client.get(f"/api/upload/{record.token}")
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "status": "pending", "reason": None}

    missing = test_client.get("/api/upload/nope")
    assert missing.json()["valid"] is False
    assert missing.json()["reason"] == "not_found"


def _run(coro):
    import asyncio

    return asyncio.run(coro)
