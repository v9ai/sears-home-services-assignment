"""Upload API + the caller-facing upload page (Tier 3).

``POST /api/upload/{token}`` accepts the photo (multipart, 10 MB cap, jpeg/png/webp
allowlist); ``GET /api/upload/{token}`` reports token validity. ``GET /upload/{token}``
serves the minimal self-contained HTML page the emailed link points at — it checks the
token via the JSON API before showing the form (so an expired/used link gets a friendly
error instead of a failed POST). Analysis runs in a background task so the response is
fast; the agent (or a follow-up email) picks up the result once ``status == 'analyzed'``.
"""

from __future__ import annotations

import asyncio
import logging
import os

import openai
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.obs import log_event
from app.uploads.store import TokenAlreadyUsedError, UploadRecord, get_store
from app.vision.pipeline import run_vision_pipeline

logger = logging.getLogger("app.uploads")

# Only these vision failures are worth retrying — a network blip, a timeout, or a
# transient rate limit may clear on a second attempt. Everything else (schema/validation
# errors, unparseable responses, programming errors) is deterministic: retrying just
# burns latency, so those fail immediately. APITimeoutError subclasses APIConnectionError
# but is listed explicitly for readability.
_TRANSIENT_VISION_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
)
# Backoff (seconds) applied *between* attempts; length == the number of retries after the
# first try. Worst-case added latency is the sum (1 + 2 = 3s), comfortably under the ~10s
# budget so the caller isn't left waiting on a doomed analysis.
_VISION_RETRY_BACKOFFS_S = (1.0, 2.0)

router = APIRouter(prefix="/api/upload", tags=["upload"])

# Caller-facing page for the emailed Tier-3 link ({APP_BASE_URL}/upload/{token}).
# Served by the backend itself so the system needs no separate frontend. The page is
# fully static — the token is read client-side from the URL path, never interpolated
# into the HTML, so there is no injection surface.
page_router = APIRouter(tags=["upload-page"])

_UPLOAD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sears Home Services — photo upload</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 30rem;
         margin: 3rem auto; padding: 0 1rem; color: #1a1a2e; }
  h1 { font-size: 1.25rem; }
  .card { border: 1px solid #ddd; border-radius: 8px; padding: 1.5rem; }
  button { background: #0f4c81; color: #fff; border: 0; border-radius: 6px;
           padding: .6rem 1.2rem; font-size: 1rem; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  #msg { margin-top: 1rem; }
  .err { color: #b00020; }
  .ok { color: #1a7f37; }
</style>
</head>
<body>
<h1>Sears Home Services</h1>
<div class="card">
  <p>Upload a photo of your appliance so our agent can take a look.</p>
  <form id="f" hidden>
    <input id="file" type="file" accept="image/jpeg,image/png,image/webp" required>
    <button id="go" type="submit">Upload photo</button>
  </form>
  <p id="msg">Checking your link…</p>
</div>
<script>
  var token = window.location.pathname.split("/").pop();
  var msg = document.getElementById("msg");
  var form = document.getElementById("f");
  var reasons = {
    expired: "This upload link has expired. Please ask the agent for a new one.",
    already_used: "This link was already used. Please ask the agent for a new one.",
    failed: "The previous analysis didn't complete. Please ask the agent for a fresh link.",
    not_found: "This upload link isn't valid. Please check the link from your email."
  };
  fetch("/api/upload/" + encodeURIComponent(token))
    .then(function (r) { return r.json(); })
    .then(function (s) {
      if (s.valid) { form.hidden = false; msg.textContent = ""; }
      else {
        msg.textContent = reasons[s.reason] || "This link can't be used.";
        msg.className = "err";
      }
    })
    .catch(function () {
      msg.textContent = "Couldn't check the link — please try again.";
      msg.className = "err";
    });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var file = document.getElementById("file").files[0];
    if (!file) return;
    document.getElementById("go").disabled = true;
    msg.textContent = "Uploading…"; msg.className = "";
    var body = new FormData();
    body.append("file", file);
    fetch("/api/upload/" + encodeURIComponent(token), { method: "POST", body: body })
      .then(function (r) {
        if (r.ok) {
          form.hidden = true;
          msg.textContent =
            "Photo received — you can return to your call. " +
            "Our agent will review it shortly.";
          msg.className = "ok";
        } else {
          return r.json().then(function (d) { throw new Error(d.detail || "Upload failed."); });
        }
      })
      .catch(function (err) {
        document.getElementById("go").disabled = false;
        msg.textContent = err.message || "Upload failed — please try again.";
        msg.className = "err";
      });
  });
</script>
</body>
</html>"""


@page_router.get("/upload/{token}", response_class=HTMLResponse, include_in_schema=False)
async def upload_page(token: str) -> HTMLResponse:
    return HTMLResponse(_UPLOAD_PAGE_HTML)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_READ_CHUNK_BYTES = 1024 * 1024  # stream uploads in 1 MB chunks; never buffer an oversize body
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
    if record.status == "failed":
        # A dead analysis is not a consumed link — don't tell the caller
        # "already used" when the right move is to re-request a link.
        return UploadStatusResponse(valid=False, status=record.status, reason="failed")
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

    # Public, unauthenticated endpoint: enforce the cap before/while reading —
    # an oversize body must never be fully materialized just to be told 413.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MB limit.")
    chunks: list[bytes] = []
    received = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        received += len(chunk)
        if received > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 10 MB limit.")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body:
        raise HTTPException(status_code=400, detail="Empty upload.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = ALLOWED_CONTENT_TYPES[content_type]
    image_path = os.path.join(UPLOAD_DIR, f"{token}.{ext}")
    with open(image_path, "wb") as fh:
        fh.write(body)

    try:
        record = await store.save_image(token, image_path)
    except TokenAlreadyUsedError:
        raise HTTPException(
            status_code=409, detail="This upload link has already been used."
        ) from None
    background_tasks.add_task(_analyze_in_background, token)
    return {"status": record.status}


async def _analyze_in_background(token: str) -> None:
    store = get_store()
    record = await store.get_by_token(token)
    if record is None:
        return

    # A vision-model failure must never leave the upload stuck at 'uploaded' forever: we
    # retry transient errors a bounded number of times, then mark the upload terminally
    # 'failed' so the agent's check_image_analysis can tell the caller honestly instead of
    # polling an analysis that will never arrive.
    max_attempts = len(_VISION_RETRY_BACKOFFS_S) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            await run_vision_pipeline(record)
            return
        except _TRANSIENT_VISION_ERRORS as exc:
            log_event(
                logger, "vision.analysis_failed", token=token, attempt=attempt, transient=True
            )
            if attempt < max_attempts:
                logger.warning(
                    "vision analysis transient failure token=%s attempt=%d/%d: %s — retrying",
                    token,
                    attempt,
                    max_attempts,
                    exc,
                )
                await asyncio.sleep(_VISION_RETRY_BACKOFFS_S[attempt - 1])
                continue
            logger.warning(
                "vision analysis failed after %d attempts token=%s: %s", max_attempts, token, exc
            )
            break
        except Exception:
            # Non-transient (schema/validation/parse/programming error): retrying is
            # pointless, so fail immediately on the first attempt.
            logger.exception("vision analysis failed (non-transient) token=%s", token)
            log_event(
                logger, "vision.analysis_failed", token=token, attempt=attempt, transient=False
            )
            break

    await store.mark_failed(token)
