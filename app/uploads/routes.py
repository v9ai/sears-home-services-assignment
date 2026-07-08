"""Upload API — thin server-side counterpart to ``web/app/upload/[token]``.

``POST /api/upload/{token}`` accepts the photo (multipart, 10 MB cap, jpeg/png/webp
allowlist); ``GET /api/upload/{token}`` lets the Next.js page check token validity
before rendering the form (so an expired/used link gets a friendly error page instead
of a failed POST). Analysis runs in a background task so the response is fast; the
agent (or a follow-up email) picks up the result once ``status == 'analyzed'``.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app.uploads.store import UploadRecord, get_store
from app.vision.pipeline import run_vision_pipeline

router = APIRouter(prefix="/api/upload", tags=["upload"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "data/uploads")


class UploadStatusResponse(BaseModel):
    valid: bool
    status: str | None = None
    reason: str | None = None


def _status_response(record: UploadRecord | None) -> UploadStatusResponse:
    if record is None:
        return UploadStatusResponse(valid=False, reason="not_found")
    if record.status == "expired":
        return UploadStatusResponse(valid=False, status=record.status, reason="expired")
    if record.status != "pending":
        return UploadStatusResponse(valid=False, status=record.status, reason="already_used")
    return UploadStatusResponse(valid=True, status=record.status)


@router.get("/{token}", response_model=UploadStatusResponse)
async def check_upload_token(token: str) -> UploadStatusResponse:
    record = await get_store().get_by_token(token)
    return _status_response(record)


@router.post("/{token}")
async def upload_photo(
    token: str, file: UploadFile, background_tasks: BackgroundTasks
) -> dict[str, str]:
    store = get_store()
    record = await store.get_by_token(token)
    if record is None:
        raise HTTPException(status_code=404, detail="Upload link not found.")
    if record.status == "expired":
        raise HTTPException(status_code=410, detail="This upload link has expired.")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="This upload link has already been used.")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG, or WebP images are accepted.",
        )

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MB limit.")
    if not body:
        raise HTTPException(status_code=400, detail="Empty upload.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = ALLOWED_CONTENT_TYPES[content_type]
    image_path = os.path.join(UPLOAD_DIR, f"{token}.{ext}")
    with open(image_path, "wb") as fh:
        fh.write(body)

    record = await store.save_image(token, image_path)
    background_tasks.add_task(_analyze_in_background, token)
    return {"status": record.status}


async def _analyze_in_background(token: str) -> None:
    store = get_store()
    record = await store.get_by_token(token)
    if record is None:
        return
    await run_vision_pipeline(record)
