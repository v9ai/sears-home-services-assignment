"""``send_image_upload_link`` / ``check_image_analysis`` — the Tier-3 agent tools.

Implements the frozen signatures in ``app.contracts`` (``SendImageUploadLink``,
``CheckImageAnalysis``): both take only the LLM-visible args (``email`` / none). Session
identity and the live case file are threaded via the same per-turn ``ContextVar``
mechanism ``core_tools.py`` (voice-diagnostic-core) uses — ``app.agent.state``'s
``current_case_file`` / ``current_session_id``, set once per turn by
``app.agent.core.run_turn``. This keeps the tool JSON schemas the LLM sees identical to
the frozen contract (no ``ctx`` parameter leaks in) and avoids a second, divergent
state-threading convention.
"""

from __future__ import annotations

import os
import uuid

from app.agent.state import get_case_file, get_session_id
from app.email.backend import get_email_backend
from app.email.templates import upload_link_email
from app.uploads.store import UploadRecord, get_store
from app.vision.merge import merge_vision_into_case_file, summarize_for_agent
from app.vision.schema import VisionAnalysis

# Fields ``merge_vision_into_case_file`` may update — copied back onto the live case
# file in place so the WS handler's persisted ``state.case_file`` reflects the merge.
_MERGE_FIELDS = ("brand", "appliance_type", "steps_given", "safety_flag")


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:3000")


async def create_and_send_upload_link(session_id: uuid.UUID, email: str) -> UploadRecord:
    """Storage + email side effect, factored out so it's testable without a live turn."""
    record = await get_store().create(session_id, email)
    link = f"{_app_base_url()}/upload/{record.token}"
    subject, body = upload_link_email(link)
    await get_email_backend().send(to=email, subject=subject, body=body)
    return record


async def send_image_upload_link(email: str) -> str:
    """Email the caller a tokenized link to `{APP_BASE_URL}/upload/{token}`."""
    session_id = get_session_id()
    if session_id is None:
        return "I couldn't find an active session to attach the photo request to."

    await create_and_send_upload_link(session_id, email)

    case_file = get_case_file()
    if case_file.customer.email != email:
        case_file.customer.email = email

    return (
        f"Sent an upload link to {email}. Ask the caller to check their email, upload a "
        "photo, and let us know when it's done — then call check_image_analysis."
    )


async def check_image_analysis() -> str:
    """Poll the latest upload for this session; fold findings into the case file once
    analysis is ready (requirements.md §Decisions #4 — polling, not a WS push)."""
    session_id = get_session_id()
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
    case_file = get_case_file()
    merged = merge_vision_into_case_file(case_file, analysis)
    if merged is not case_file:
        for field in _MERGE_FIELDS:
            setattr(case_file, field, getattr(merged, field))
    return summarize_for_agent(analysis)


TOOLS: list = [send_image_upload_link, check_image_analysis]
