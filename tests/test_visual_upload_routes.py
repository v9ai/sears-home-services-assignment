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


def test_upload_empty_body_400(client):
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", b"", "image/jpeg")},
    )
    assert resp.status_code == 400


def test_upload_missing_content_type_is_rejected(client):
    """A part with no content-type can't be allow-listed, so it's a 415, not a 500."""
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo", JPEG_BYTES, "")},
    )
    assert resp.status_code == 415


@pytest.mark.parametrize(
    ("filename", "content_type", "expected_ext", "magic"),
    [
        ("photo.jpg", "image/jpeg", "jpg", b"\xff\xd8\xff"),
        ("photo.png", "image/png", "png", b"\x89PNG\r\n"),
        ("photo.webp", "image/webp", "webp", b"RIFF----WEBP"),
    ],
)
def test_upload_persists_exact_bytes_with_correct_extension(
    client, filename, content_type, expected_ext, magic
):
    """Stored-object integrity: the file lands at ``{token}.{ext}`` chosen from the
    content-type allowlist, and its bytes are exactly what was posted."""
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    payload = magic + b"payload-bytes"
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": (filename, payload, content_type)},
    )
    assert resp.status_code == 200

    stored = _run(store.get_by_token(record.token))
    assert stored is not None
    assert stored.image_path.endswith(f"{record.token}.{expected_ext}")
    with open(stored.image_path, "rb") as fh:
        assert fh.read() == payload


def test_get_status_reports_expired_and_used_reasons(client):
    test_client, store = client

    expired = _run(store.create(uuid.uuid4(), "caller@example.com"))
    store._by_token[expired.token] = expired.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    body = test_client.get(f"/api/upload/{expired.token}").json()
    assert body == {"valid": False, "status": "expired", "reason": "expired"}

    used = _run(store.create(uuid.uuid4(), "caller@example.com"))
    _run(store.save_image(used.token, "data/uploads/x.jpg"))
    body = test_client.get(f"/api/upload/{used.token}").json()
    assert body["valid"] is False
    assert body["reason"] == "already_used"
    assert body["status"] == "uploaded"


def test_upload_rejects_second_attempt_after_expiry(client):
    """A link that expired before any photo arrived must 410, never accept a late upload."""
    test_client, store = client
    record = _run(store.create(uuid.uuid4(), "caller@example.com"))
    store._by_token[record.token] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    resp = test_client.post(
        f"/api/upload/{record.token}",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 410
    # Nothing was stored for the expired link.
    stored = _run(store.get_by_token(record.token))
    assert stored is not None and stored.image_path is None


def _run(coro):
    import asyncio

    return asyncio.run(coro)
