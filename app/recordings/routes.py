"""Read-only recordings API — call transcript + audio replay, no auth.

specs/features/2026-07-08-call-recording-replay/requirements.md: list/detail/audio
endpoints over the existing `sessions` table (jsonb `transcript`/`case_file`); no new
metadata table (Decision 4) — audio file paths are derived from `session_id` +
`audio_seq` by convention (Decision 4), not looked up.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.agent import tts
from app.contracts import CaseFile
from app.db.base import get_sessionmaker
from app.db.models_core import SessionRecord

router = APIRouter(prefix="/api/recordings", tags=["recordings"])

RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")

# web writes mp3 (streamed OpenAI TTS), phone writes wav (PCM16 wrapped) — the audio
# endpoint probes both since the extension isn't tracked in the DB (Decision 4).
_AUDIO_EXTENSIONS = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def _tts_fallback_enabled() -> bool:
    return os.environ.get("REPLAY_TTS_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class RecordingListItem(BaseModel):
    id: uuid.UUID
    channel: str
    started_at: datetime
    ended_at: datetime | None
    appliance_type: str | None
    turn_count: int


class RecordingTranscriptTurn(BaseModel):
    role: str
    text: str
    ts: str | None = None
    has_audio: bool
    audio_seq: int | None = None


class RecordingDetail(BaseModel):
    transcript: list[RecordingTranscriptTurn]
    case_file: CaseFile


@router.get("", response_model=list[RecordingListItem])
async def list_recordings(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[RecordingListItem]:
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        stmt = (
            select(SessionRecord)
            .order_by(SessionRecord.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        records = result.scalars().all()
    return [
        RecordingListItem(
            id=record.id,
            channel=record.channel,
            started_at=record.started_at,
            ended_at=record.ended_at,
            appliance_type=record.appliance_type,
            turn_count=len(record.transcript or []),
        )
        for record in records
    ]


@router.get("/{recording_id}", response_model=RecordingDetail)
async def get_recording(recording_id: uuid.UUID) -> RecordingDetail:
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        record = await db.get(SessionRecord, recording_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    turns = [
        RecordingTranscriptTurn(
            role=entry.get("role", ""),
            text=entry.get("text", ""),
            ts=entry.get("ts"),
            has_audio=entry.get("audio_seq") is not None,
            audio_seq=entry.get("audio_seq"),
        )
        for entry in (record.transcript or [])
    ]
    case_file = CaseFile.model_validate(record.case_file or {})
    return RecordingDetail(transcript=turns, case_file=case_file)


@router.get("/{recording_id}/audio/{seq}")
async def get_recording_audio(recording_id: uuid.UUID, seq: int):
    for ext, media_type in _AUDIO_EXTENSIONS.items():
        path = os.path.join(RECORDINGS_DIR, str(recording_id), f"{seq:05d}.{ext}")
        if os.path.exists(path):
            return FileResponse(path, media_type=media_type)
    if _tts_fallback_enabled():
        return await _resynthesize_audio(recording_id, seq)
    raise HTTPException(status_code=404, detail="Recording audio not found.")


async def _resynthesize_audio(recording_id: uuid.UUID, seq: int) -> StreamingResponse:
    """`REPLAY_TTS_FALLBACK` on: re-synthesize a turn whose audio was never stored,
    from its persisted transcript text (Decision 1 — flagged, off by default)."""
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        record = await db.get(SessionRecord, recording_id)
    text = None
    if record is not None:
        for entry in record.transcript or []:
            if entry.get("audio_seq") == seq:
                text = entry.get("text")
                break
    if not text or not text.strip():
        raise HTTPException(status_code=404, detail="Recording audio not found.")
    return StreamingResponse(tts.synthesize(text, response_format="mp3"), media_type="audio/mpeg")
