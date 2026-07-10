"""Upload size-cap enforcement without full-body buffering (bugfix-loop B2).

`POST /api/upload/{token}` is public and unauthenticated. Before the fix the
handler did `body = await file.read()` and only then compared against
``MAX_UPLOAD_BYTES`` — an oversize body was fully materialized in memory just
to be told 413. These tests pin the hardened contract: a declared-oversize
upload is rejected before any read, and an undeclared-size stream is rejected
as soon as the cap is crossed, never consumed to the end.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.uploads.routes import MAX_UPLOAD_BYTES, upload_photo
from app.uploads.store import InMemoryUploadStore, set_store


class _CountingFile:
    """UploadFile stand-in that serves ``total`` bytes in fixed chunks and
    records how much the handler actually consumed."""

    def __init__(self, total: int, size: int | None = None, chunk: int = 1024 * 1024):
        self.content_type = "image/jpeg"
        self.size = size
        self._remaining = total
        self._chunk = chunk
        self.bytes_served = 0
        self.read_calls = 0

    async def read(self, n: int = -1) -> bytes:
        self.read_calls += 1
        want = self._chunk if n is None or n < 0 else min(n, self._chunk)
        take = min(want, self._remaining)
        self._remaining -= take
        self.bytes_served += take
        return b"x" * take


@pytest.fixture
async def pending_token() -> str:
    store = InMemoryUploadStore()
    set_store(store)
    record = await store.create(session_id=uuid.uuid4(), email="caller@example.com")
    return record.token


async def test_declared_oversize_rejected_without_any_read(pending_token: str) -> None:
    file = _CountingFile(total=50 * 1024 * 1024, size=50 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc:
        await upload_photo(pending_token, file, BackgroundTasks())
    assert exc.value.status_code == 413
    assert file.read_calls == 0
    assert file.bytes_served == 0


async def test_undeclared_oversize_stops_reading_at_the_cap(pending_token: str) -> None:
    # No declared size (chunked transfer): the handler must stop pulling bytes
    # as soon as the cap is crossed instead of draining all 50 MB.
    total = 50 * 1024 * 1024
    file = _CountingFile(total=total, size=None)
    with pytest.raises(HTTPException) as exc:
        await upload_photo(pending_token, file, BackgroundTasks())
    assert exc.value.status_code == 413
    # Allow one chunk of slack past the cap; anything near `total` means the
    # body was fully buffered before the check (the original bug).
    assert file.bytes_served <= MAX_UPLOAD_BYTES + 2 * 1024 * 1024
    assert file.bytes_served < total // 2


async def test_exactly_at_cap_is_accepted(pending_token: str, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.uploads.routes.UPLOAD_DIR", str(tmp_path))
    file = _CountingFile(total=MAX_UPLOAD_BYTES, size=MAX_UPLOAD_BYTES)
    result = await upload_photo(pending_token, file, BackgroundTasks())
    assert result == {"status": "uploaded"}
    assert file.bytes_served == MAX_UPLOAD_BYTES


async def test_empty_upload_still_400(pending_token: str) -> None:
    file = _CountingFile(total=0, size=0)
    with pytest.raises(HTTPException) as exc:
        await upload_photo(pending_token, file, BackgroundTasks())
    assert exc.value.status_code == 400
