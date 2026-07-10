"""Upload endpoint security edges (bugfix-loop T14).

Three previously-unpinned behaviors on the public, unauthenticated upload
endpoint: path-traversal-shaped tokens must resolve to 404 (and write
nothing), the declared-content-type trust decision is pinned explicitly, and
the single-use gate must hold under concurrency — before the fix two
interleaved uploads on one pending token could BOTH return 200 (check-then-
write race across awaits); the store now claims the token atomically and the
loser gets 409.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.uploads.routes import router, upload_photo
from app.uploads.store import InMemoryUploadStore, set_store


@pytest.fixture
def store():
    store = InMemoryUploadStore()
    set_store(store)
    return store


@pytest.fixture
def client(store) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class _SlowFile:
    """Small valid upload whose read() yields the loop once — guarantees the
    two racing handlers interleave across the check/save awaits."""

    content_type = "image/jpeg"
    size = 4

    async def read(self, n: int = -1) -> bytes:
        await asyncio.sleep(0)
        if getattr(self, "_done", False):
            return b""
        self._done = True
        return b"\xff\xd8\xff\xe0"


# --- path traversal ---------------------------------------------------------------


@pytest.mark.parametrize("token", ["..%2F..%2Fetc%2Fpasswd", "..", ".%2E", "a..b"])
async def test_traversal_shaped_tokens_resolve_404_and_write_nothing(
    client, store, token, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("app.uploads.routes.UPLOAD_DIR", str(tmp_path))
    response = client.post(
        f"/api/upload/{token}",
        files={"file": ("x.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
    )
    assert response.status_code == 404
    assert list(tmp_path.iterdir()) == []


async def test_slash_bearing_token_never_reaches_the_handler(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.uploads.routes.UPLOAD_DIR", str(tmp_path))
    response = client.post(
        "/api/upload/../../secrets",
        files={"file": ("x.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
    )
    assert response.status_code in (404, 405)
    assert list(tmp_path.iterdir()) == []


# --- declared-content-type trust (pinned decision) ---------------------------------


async def test_mismatched_bytes_are_accepted_under_the_declared_type(
    client, store, tmp_path, monkeypatch
) -> None:
    # PINNED DECISION: the endpoint trusts the declared content type; bytes are
    # not sniffed. The file is stored under the declared extension and only
    # ever consumed by the vision model (never served back or executed), so
    # polyglot risk is bounded. Revisit if uploads are ever re-served.
    monkeypatch.setattr("app.uploads.routes.UPLOAD_DIR", str(tmp_path))

    async def _noop_analysis(token: str) -> None:
        return None

    # TestClient runs BackgroundTasks synchronously — never let the 200 path
    # kick off a real vision analysis.
    monkeypatch.setattr("app.uploads.routes._analyze_in_background", _noop_analysis)
    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 8
    response = client.post(
        f"/api/upload/{record.token}",
        files={"file": ("odd.jpg", png_bytes, "image/jpeg")},
    )
    assert response.status_code == 200
    stored = tmp_path / f"{record.token}.jpg"
    assert stored.read_bytes() == png_bytes


# --- single-use TOCTOU --------------------------------------------------------------


async def test_concurrent_uploads_on_one_token_accept_exactly_one(
    store, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("app.uploads.routes.UPLOAD_DIR", str(tmp_path))
    record = await store.create(session_id=uuid.uuid4(), email="a@b.co")

    async def attempt() -> int:
        try:
            await upload_photo(record.token, _SlowFile(), BackgroundTasks())
            return 200
        except HTTPException as exc:
            return exc.status_code

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == [200, 409], f"single-use must hold under concurrency, got {results}"
    assert (await store.get_by_token(record.token)).status == "uploaded"
