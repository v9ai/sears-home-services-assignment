"""Session case-file + memory persistence — durability across WS reconnects.

A `/ws/call` client keeps its own ``session_id`` (any stable id it generates once)
and passes it on every connect. This is what makes
"reload the tab mid-session and the agent resumes without re-asking" possible without
adding a new WS frame type to the frozen contract: the session id travels in the
connect URL's query string, not over the frame protocol.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.memory import ChatMemoryBuffer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.core import get_llm
from app.contracts import CaseFile
from app.db.models_core import SessionRecord


@dataclass
class SessionState:
    session_id: uuid.UUID
    case_file: CaseFile
    memory: ChatMemoryBuffer
    transcript: list[dict[str, str]] = field(default_factory=list)
    is_new: bool = True
    # `time.monotonic()` of the last tool-call filler fired on this session, or None if
    # none has. Read by the web bridge's filler debounce (app/ws/routes.py) so rapid
    # consecutive turns don't stack overlapping fillers. Session-scoped, never persisted.
    last_filler_at: float | None = None


def _memory_from_transcript(transcript: list[dict[str, str]]) -> ChatMemoryBuffer:
    memory = ChatMemoryBuffer.from_defaults(llm=get_llm())
    if transcript:
        messages = [
            ChatMessage(
                role="user" if line["role"] == "user" else "assistant",
                content=line["text"],
            )
            for line in transcript
        ]
        memory.put_messages(messages)
    return memory


async def load_or_create_session(db: AsyncSession, session_id: str | None) -> SessionState:
    """Load a session by id, or create a fresh one (using the client-supplied id if given)."""
    parsed_id: uuid.UUID | None = None
    if session_id:
        try:
            parsed_id = uuid.UUID(session_id)
        except ValueError:
            parsed_id = None
        if parsed_id is not None:
            record = await db.get(SessionRecord, parsed_id)
            if record is not None:
                case_file = CaseFile.model_validate(record.case_file or {})
                transcript = list(record.transcript or [])
                return SessionState(
                    session_id=record.id,
                    case_file=case_file,
                    memory=_memory_from_transcript(transcript),
                    transcript=transcript,
                    is_new=False,
                )
    # Reuse the already-parsed id: `parsed_id` is None for both a missing id and a
    # malformed one, so a garbage `?session_id` query param degrades to a fresh session
    # instead of re-raising ValueError into the /ws/call connect. Re-parsing `session_id`
    # here would crash on exactly the malformed input the resume branch already tolerated.
    new_id = parsed_id or uuid.uuid4()
    record = SessionRecord(id=new_id, channel="web")
    db.add(record)
    await db.commit()
    return SessionState(
        session_id=new_id,
        case_file=CaseFile(),
        memory=_memory_from_transcript([]),
        transcript=[],
        is_new=True,
    )


async def persist_session(db: AsyncSession, state: SessionState) -> None:
    """Write the current case file + transcript back to Postgres."""
    record = await db.get(SessionRecord, state.session_id)
    if record is None:
        record = SessionRecord(id=state.session_id, channel="web")
        db.add(record)
    record.case_file = state.case_file.model_dump(mode="json")
    record.appliance_type = state.case_file.appliance_type
    record.transcript = state.transcript
    await db.commit()
