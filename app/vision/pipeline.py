"""End-to-end vision pipeline: analyze → merge into the session case file → persist.

Runs as a FastAPI background task right after upload (``app/uploads/routes.py``). Reads
and writes ``sessions.case_file`` through the minimal cross-feature reference in
``app.db.models_visual.sessions_ref`` (owned by voice-diagnostic-core's rev
``0001_core`` schema) — best-effort: if the sessions table isn't reachable yet (e.g.
this worktree running standalone before integration, COORDINATION.md §4), the pipeline
still analyzes the image and updates ``image_uploads`` so ``check_image_analysis`` and
tests keep working; it just can't durably merge into a session that doesn't exist yet.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from app.contracts import CaseFile
from app.db.models_visual import sessions_ref
from app.email.backend import get_email_backend
from app.email.templates import findings_followup_email
from app.uploads.db import connect
from app.uploads.store import UploadRecord, get_store
from app.vision.client import analyze_image
from app.vision.merge import merge_vision_into_case_file
from app.vision.schema import VisionAnalysis

logger = logging.getLogger(__name__)


async def _load_session_case_file(session_id) -> tuple[CaseFile, bool]:
    """Returns (case_file, session_has_ended). Falls back to an empty case file if the
    sessions table isn't reachable (standalone/parallel-dev runs)."""
    try:
        async with connect() as conn:
            row = (
                await conn.execute(
                    sa.select(sessions_ref.c.case_file, sessions_ref.c.ended_at).where(
                        sessions_ref.c.id == session_id
                    )
                )
            ).fetchone()
    except Exception:  # noqa: BLE001 - sessions table may not exist yet in this worktree
        logger.debug("sessions table unavailable; using an empty case file", exc_info=True)
        return CaseFile(), False

    if row is None:
        return CaseFile(), False
    case_file = CaseFile.model_validate(row.case_file or {})
    return case_file, row.ended_at is not None


async def _persist_session_case_file(session_id, case_file: CaseFile) -> None:
    try:
        async with connect() as conn:
            await conn.execute(
                sa.update(sessions_ref)
                .where(sessions_ref.c.id == session_id)
                .values(case_file=case_file.model_dump(mode="json"))
            )
    except Exception:  # noqa: BLE001 - see _load_session_case_file
        logger.debug("could not persist merged case file to sessions", exc_info=True)


async def run_vision_pipeline(
    upload: UploadRecord, analysis: VisionAnalysis | None = None
) -> VisionAnalysis:
    """Analyze ``upload.image_path``, merge findings into the session case file, mark
    the upload ``analyzed``, and email findings if the call has already ended.

    ``analysis`` lets tests inject a canned result and skip the OpenAI call entirely.
    """
    case_file, session_ended = await _load_session_case_file(upload.session_id)

    if analysis is None:
        assert upload.image_path is not None, "cannot analyze an upload with no image"
        analysis = await analyze_image(upload.image_path, case_file)

    merged = merge_vision_into_case_file(case_file, analysis)
    await _persist_session_case_file(upload.session_id, merged)

    store = get_store()
    await store.save_analysis(upload.token, analysis.model_dump(mode="json"))

    if session_ended:
        subject, body = findings_followup_email(analysis)
        await get_email_backend().send(to=upload.email, subject=subject, body=body)

    return analysis
