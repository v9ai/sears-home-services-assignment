"""Full-call recording for the Pipecat voice bot.

The web channel (`app/ws/routes.py`) records per-turn WAVs and persists a `sessions` row;
the Pipecat phone channel historically did neither, so phone calls produced no app-side
audio and never appeared in `GET /api/recordings`. This module supplies the two pieces the
bot (`app/voice/bot.py`) wires in:

1. `write_stereo_wav` — persist the `AudioBufferProcessor` composite (caller = left channel,
   bot = right channel) as one WAV per call at `{RECORDINGS_DIR}/{session_id}/call.wav`, the
   same directory convention the recordings API already serves from
   (`app/recordings/routes.py`). The mono `app/phone/stt.py::pcm16_to_wav_bytes` can't write
   two channels, hence a dedicated writer here.
2. `persist_voice_session` — upsert a `SessionRecord` (channel `"phone"`, `call_sid`,
   `case_file`, transcript) so the call lists/replays in the existing recordings UI. Mirrors
   `app/agent/session_store.py::persist_session`, reading the conversation off the pipeline's
   `LLMContext` (the Pipecat replacement for the LlamaIndex `ChatMemoryBuffer`).
3. `ensure_voice_session_row` — insert the minimal `sessions` row at call START
   (2026-07-09-booking-session-attribution): mid-call tools that attribute rows to the
   session (`book_appointment` → `appointments.session_id` FK) need the row to exist
   before disconnect; `persist_voice_session` remains the owner of the full end-of-call
   update, and both sides get-or-create the same deterministic `uuid5(CallSid)` PK.

Everything here is best-effort (spec 2026-07-08-call-recording-replay Decision 5): recording
must never disturb the live call, so callers wrap these in try/except and swallow failures.
"""

from __future__ import annotations

import logging
import os
import wave

from app.contracts import CaseFile
from app.db.base import get_sessionmaker
from app.db.models_core import SessionRecord
from app.obs import log_event

logger = logging.getLogger("app.voice.recording")

RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "data/recordings")
CALL_AUDIO_FILENAME = "call.wav"


def recording_enabled() -> bool:
    """`VOICE_RECORDING_ENABLED` (default on) — mirrors `TWILIO_CALL_RECORDING_ENABLED`."""
    return os.environ.get("VOICE_RECORDING_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def call_recording_path(session_id) -> str:
    """`{RECORDINGS_DIR}/{session_id}/call.wav` — the one full-call file per call. The recordings
    API (`app/recordings/routes.py`) derives the same path from the session/recording id."""
    return os.path.join(RECORDINGS_DIR, str(session_id), CALL_AUDIO_FILENAME)


def write_stereo_wav(path: str, pcm: bytes, sample_rate: int, num_channels: int) -> None:
    """Wrap interleaved PCM16 in a WAV container. `num_channels=2` keeps the
    AudioBufferProcessor's caller-left / bot-right composite intact for replay."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(2)  # PCM16
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


def transcript_from_context(context) -> list[dict]:  # noqa: ANN001 — pipecat LLMContext
    """Map the pipeline's `LLMContext` messages to the recordings transcript shape
    (`{"role": "user"|"agent", "text": str}`), matching what the web channel persists and what
    `app/recordings/routes.py` / the web UI expect. Drops the system prompt, tool-call and
    tool-result messages, and any non-string/empty content.

    Consecutive identical turns are collapsed: the greeting reaches the context twice — once
    seeded by `_on_connected` (so the model knows it greeted even if the caller barges in) and
    once when the assistant aggregator records the spoken `TTSSpeakFrame` text — and persisting
    both shows a doubled first line in the replay UI. Only *adjacent* duplicates are collapsed;
    a caller legitimately repeating themselves later stays intact."""
    transcript: list[dict] = []
    for message in context.get_messages():
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant"):
            continue  # skip system + tool-result messages
        if not isinstance(content, str) or not content.strip():
            continue  # skip tool-call turns (content is None / structured)
        turn = {"role": "user" if role == "user" else "agent", "text": content}
        if transcript and transcript[-1] == turn:
            continue  # collapse the double-seeded greeting (and any other adjacent echo)
        transcript.append(turn)
    return transcript


async def persist_voice_session(session, context, started_at, ended_at) -> None:  # noqa: ANN001
    """Upsert the `sessions` row for this phone call so it shows in `GET /api/recordings`.

    `SessionRecord.id == session.session_id` (a deterministic `uuid5(call_sid)`), so the row and
    the on-disk `{session_id}/call.wav` line up without any lookup table (spec Decision 4)."""
    case_file = session.case_file if isinstance(session.case_file, CaseFile) else CaseFile()
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        record = await db.get(SessionRecord, session.session_id)
        if record is None:
            record = SessionRecord(id=session.session_id, channel="phone")
            db.add(record)
        record.channel = "phone"
        record.call_sid = session.call_sid
        record.case_file = case_file.model_dump(mode="json")
        record.appliance_type = case_file.appliance_type
        record.transcript = transcript_from_context(context)
        record.started_at = started_at
        record.ended_at = ended_at
        await db.commit()


async def ensure_voice_session_row(session) -> None:  # noqa: ANN001
    """Get-or-create the minimal `sessions` row at call start (module docstring item 3).

    Runs as a background task off the greeting critical path; a booking mid-call needs
    the FK target (`appointments.session_id → sessions.id`) to exist before the
    end-of-call `persist_voice_session` upsert. Best-effort: any failure is logged as
    `voice.session_row.ensure_failed` and the booking path degrades to an
    unattributed (NULL) insert rather than an error."""
    try:
        session_factory = get_sessionmaker()
        async with session_factory() as db:
            record = await db.get(SessionRecord, session.session_id)
            if record is None:
                db.add(
                    SessionRecord(id=session.session_id, channel="phone", call_sid=session.call_sid)
                )
                await db.commit()
    except Exception as exc:
        log_event(logger, "voice.session_row.ensure_failed", error=type(exc).__name__)
