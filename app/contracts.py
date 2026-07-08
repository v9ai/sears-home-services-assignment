"""Frozen contracts shared by every feature triplet.

Changing anything here is a constitution-revising change (COORDINATION.md §2):
coordinate before editing. Parallel feature agents import from this module; they
never redefine these shapes.

Contents:
- ``Appliance`` — the six supported appliance types.
- ``CaseFile`` (+ ``Symptom``, ``Customer``) — the session case file, persisted as
  ``sessions.case_file`` jsonb and injected into the agent prompt every turn.
- WS frames — ``UserTextFrame`` in; ``TranscriptFrame`` / ``AudioFrame`` /
  ``StateFrame`` out over ``/ws/call``.
- ``SessionBridge`` — the transport-agnostic session interface the web WS bridge and
  the Twilio Media Streams adapter both implement.
- Tool signature protocols — declarations only; owning features implement the real
  async functions and expose them via ``app.tools`` auto-discovery.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Appliance = Literal["washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac"]
"""The six appliance types the agent supports."""


class Symptom(BaseModel):
    """A single reported symptom captured into the case file."""

    description: str
    onset: str
    error_code: str | None = None
    sound: str | None = None


class Customer(BaseModel):
    """Caller identity as accumulated during the conversation. All fields optional."""

    name: str | None = None
    zip: str | None = None
    email: str | None = None


class CaseFile(BaseModel):
    """Structured session memory — the never-re-ask non-negotiable made structural.

    Injected into the agent's system prompt every turn and persisted as
    ``sessions.case_file`` jsonb.
    """

    appliance_type: Appliance | None = None
    brand: str | None = None
    model: str | None = None
    symptoms: list[Symptom] = Field(default_factory=list)
    safety_flag: bool = False
    steps_given: list[str] = Field(default_factory=list)
    customer: Customer = Field(default_factory=Customer)


# --- WebSocket frames (/ws/call) -------------------------------------------------


class UserTextFrame(BaseModel):
    """Client → server: a typed caller utterance."""

    type: Literal["user_text"] = "user_text"
    text: str


class TranscriptFrame(BaseModel):
    """Server → client: a transcript line for either speaker."""

    type: Literal["transcript"] = "transcript"
    role: Literal["user", "agent"]
    text: str


class AudioFrame(BaseModel):
    """Server → client: one base64 TTS audio chunk, ordered by ``seq``."""

    type: Literal["audio"] = "audio"
    chunk: str
    seq: int


class StateFrame(BaseModel):
    """Server → client: the current case file for the state panel."""

    type: Literal["state"] = "state"
    case_file: CaseFile


# --- Session bridge --------------------------------------------------------------


@runtime_checkable
class SessionBridge(Protocol):
    """Transport-agnostic session interface.

    The Phase 1 web WS bridge and the Phase 5 Twilio Media Streams adapter are two
    implementations; the agent layer talks only to this protocol.
    """

    async def receive_user_utterance(self, text: str, audio_seq: int | None = None) -> None: ...

    async def emit_transcript(self, role: str, text: str) -> None: ...

    async def emit_audio(self, chunk: bytes) -> None: ...


# --- Tool signatures -------------------------------------------------------------
# Declarations only. Owning features (COORDINATION.md §3) implement the real async
# functions in their own ``app/tools/*_tools.py`` and expose them via a module-level
# ``TOOLS`` list picked up by ``app.tools.registry``. These protocols document the
# frozen call shapes; they are not the implementations.


class IdentifyAppliance(Protocol):
    async def __call__(self, appliance_type: str) -> str: ...


class RecordSymptom(Protocol):
    async def __call__(
        self,
        description: str,
        onset: str | None = None,
        error_code: str | None = None,
        sound: str | None = None,
    ) -> str: ...


class GetTroubleshootingSteps(Protocol):
    async def __call__(self, appliance: Appliance, symptom_key: str) -> str: ...


class UpdateCaseFile(Protocol):
    async def __call__(self, **fields: object) -> str: ...


class FindTechnicians(Protocol):
    async def __call__(
        self, zip: str, appliance_type: Appliance, window: str | None = None
    ) -> str: ...


class BookAppointment(Protocol):
    async def __call__(self, slot_id: str, customer: Customer, issue_summary: str) -> str: ...


class SendImageUploadLink(Protocol):
    async def __call__(self, email: str) -> str: ...


class CheckImageAnalysis(Protocol):
    async def __call__(self) -> str: ...
