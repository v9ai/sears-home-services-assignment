"""Read-only recordings API — call transcript + audio replay, no auth.

specs/features/2026-07-08-call-recording-replay/requirements.md: list/detail/audio
endpoints over the existing `sessions` table (jsonb `transcript`/`case_file`); no new
metadata table (Decision 4) — audio file paths are derived from `session_id` +
`audio_seq` by convention (Decision 4), not looked up.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.agent import tts
from app.contracts import CaseFile
from app.db.base import get_sessionmaker
from app.db.models_core import SessionRecord
from app.phone.twilio_client import TwilioConfigError, get_twilio_client

router = APIRouter(prefix="/api/recordings", tags=["recordings"])
logger = logging.getLogger("app.recordings")

RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")
TWILIO_RECORDING_MEDIA_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording_sid}.mp3"
)

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
    has_call_sid: bool


class RecordingTranscriptTurn(BaseModel):
    role: str
    text: str
    ts: str | None = None
    has_audio: bool
    audio_seq: int | None = None


class TwilioRecordingInfo(BaseModel):
    sid: str
    status: str | None
    duration_seconds: int | None
    channels: int | None
    date_created: datetime | None
    media_url: str


class RecordingDetail(BaseModel):
    transcript: list[RecordingTranscriptTurn]
    case_file: CaseFile
    twilio_recordings: list[TwilioRecordingInfo] = []


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
            has_call_sid=bool(record.call_sid),
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
    twilio_recordings = (
        _fetch_twilio_recordings(recording_id, record.call_sid) if record.call_sid else []
    )
    return RecordingDetail(
        transcript=turns, case_file=case_file, twilio_recordings=twilio_recordings
    )


def _fetch_twilio_recordings(recording_id: uuid.UUID, call_sid: str) -> list[TwilioRecordingInfo]:
    """Live lookup against Twilio's Recordings resource (no local cache/table --
    Decision 4 convention). Best-effort: a Twilio API/config error should not break
    the rest of the recording detail page."""
    try:
        client = get_twilio_client()
        recordings = client.recordings.list(call_sid=call_sid)
    except TwilioConfigError:
        logger.warning("twilio_not_configured recording_id=%s", recording_id)
        return []
    except Exception:
        logger.exception("twilio_recordings_lookup_failed recording_id=%s", recording_id)
        return []
    return [
        TwilioRecordingInfo(
            sid=rec.sid,
            status=str(rec.status) if rec.status else None,
            duration_seconds=int(rec.duration) if rec.duration else None,
            channels=rec.channels,
            date_created=rec.date_created,
            media_url=f"/api/recordings/{recording_id}/twilio-audio/{rec.sid}",
        )
        for rec in recordings
    ]


@router.get("/{recording_id}/twilio-audio/{twilio_recording_sid}")
async def get_twilio_recording_audio(recording_id: uuid.UUID, twilio_recording_sid: str):
    """Proxies Twilio's recording media, since it requires HTTP Basic Auth with the
    Account SID/Auth Token -- credentials that must never reach the browser."""
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        record = await db.get(SessionRecord, recording_id)
    if record is None or not record.call_sid:
        raise HTTPException(status_code=404, detail="Recording not found.")

    try:
        client = get_twilio_client()
    except TwilioConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Confirm this recording SID actually belongs to this session's call before
    # proxying anything -- prevents an arbitrary recording_sid from being fetched
    # through this endpoint using our credentials.
    owned_sids = {rec.sid for rec in client.recordings.list(call_sid=record.call_sid)}
    if twilio_recording_sid not in owned_sids:
        raise HTTPException(status_code=404, detail="Recording audio not found.")

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    media_url = TWILIO_RECORDING_MEDIA_URL.format(
        account_sid=account_sid, recording_sid=twilio_recording_sid
    )

    async def _stream():
        async with httpx.AsyncClient(auth=(account_sid, auth_token), timeout=30.0) as http_client:
            async with http_client.stream("GET", media_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(_stream(), media_type="audio/mpeg")


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
