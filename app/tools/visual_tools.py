"""``send_image_upload_link`` / ``check_image_analysis`` — the Tier-3 agent tools.

Implements the frozen signatures in ``app.contracts`` (``SendImageUploadLink``,
``CheckImageAnalysis``): both take only the LLM-visible args (``email`` / none). Session
identity and the live case file are carried via the LlamaIndex workflow ``Context``,
which ``FunctionTool`` auto-injects for any parameter annotated ``Context`` without
exposing it in the tool's JSON schema — the same mechanism ``core_tools.py``
(voice-diagnostic-core) uses to thread the case file through every tool call.

Convention assumed (not in ``app.contracts`` — no shared session-context contract
exists yet): ``ctx.store`` keys ``"session_id"`` (str/UUID) and ``"case_file"`` (the
``CaseFile`` dict). Flagged in plan.md § Integration deltas for the lead to reconcile
against whatever key names ``core_tools.py`` actually settles on.
"""

from __future__ import annotations

import os
import uuid

from llama_index.core.workflow import Context

from app.contracts import CaseFile
from app.email.backend import get_email_backend
from app.email.templates import upload_link_email
from app.uploads.store import UploadRecord, get_store
from app.vision.merge import merge_vision_into_case_file, summarize_for_agent
from app.vision.schema import VisionAnalysis

SESSION_ID_KEY = "session_id"
CASE_FILE_KEY = "case_file"


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:3000")


async def _get_session_id(ctx: Context) -> uuid.UUID | None:
    raw = await ctx.store.get(SESSION_ID_KEY, default=None)
    if raw is None:
        return None
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def _get_case_file(ctx: Context) -> CaseFile:
    raw = await ctx.store.get(CASE_FILE_KEY, default=None)
    return CaseFile.model_validate(raw) if raw else CaseFile()


async def _set_case_file(ctx: Context, case_file: CaseFile) -> None:
    await ctx.store.set(CASE_FILE_KEY, case_file.model_dump(mode="json"))


async def create_and_send_upload_link(session_id: uuid.UUID, email: str) -> UploadRecord:
    """Storage + email side effect, factored out so it's testable without a ``Context``."""
    record = await get_store().create(session_id, email)
    link = f"{_app_base_url()}/upload/{record.token}"
    subject, body = upload_link_email(link)
    await get_email_backend().send(to=email, subject=subject, body=body)
    return record


async def send_image_upload_link(ctx: Context, email: str) -> str:
    """Email the caller a tokenized link to `{APP_BASE_URL}/upload/{token}`."""
    session_id = await _get_session_id(ctx)
    if session_id is None:
        return "I couldn't find an active session to attach the photo request to."

    await create_and_send_upload_link(session_id, email)

    case_file = await _get_case_file(ctx)
    if case_file.customer.email != email:
        updated_customer = case_file.customer.model_copy(update={"email": email})
        await _set_case_file(ctx, case_file.model_copy(update={"customer": updated_customer}))

    return (
        f"Sent an upload link to {email}. Ask the caller to check their email, upload a "
        "photo, and let us know when it's done — then call check_image_analysis."
    )


async def check_image_analysis(ctx: Context) -> str:
    """Poll the latest upload for this session; fold findings into the case file once
    analysis is ready (requirements.md §Decisions #4 — polling, not a WS push)."""
    session_id = await _get_session_id(ctx)
    if session_id is None:
        return "No active session to check."

    upload = await get_store().latest_for_session(session_id)
    if upload is None:
        return "No photo upload has been requested yet for this call."
    if upload.status == "expired":
        return "The upload link expired before a photo was received. I can send a new one."
    if upload.status == "pending":
        return "No photo has been uploaded yet — ask the caller to use the link we emailed them."
    if upload.status == "uploaded":
        return "The photo was received and is still being analyzed — please check again shortly."

    analysis = VisionAnalysis.model_validate(upload.vision_analysis or {})
    case_file = await _get_case_file(ctx)
    merged = merge_vision_into_case_file(case_file, analysis)
    if merged != case_file:
        await _set_case_file(ctx, merged)
    return summarize_for_agent(analysis)


TOOLS: list = [send_image_upload_link, check_image_analysis]
