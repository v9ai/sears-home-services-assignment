"""The Twilio Media Streams session bridge.

``TwilioMediaBridge`` implements ``app.contracts.SessionBridge`` -- the same interface
the Phase 1 web WS bridge implements -- so the agent layer (real or ``FakeAgent``,
COORDINATION.md §4) is untouched by the phone channel's audio plumbing:

- Inbound: the caller's Twilio ``media`` frames are mu-law-decoded, VAD-segmented into
  turns (:mod:`app.phone.vad`), and the completed turn is transcribed
  (:mod:`app.phone.stt`) before ``receive_user_utterance(text)`` hands it to the agent.
- Outbound: whatever the agent passes to ``emit_audio`` is resampled to 8 kHz, mu-law
  encoded, 20 ms-framed, and streamed back as Twilio ``media`` messages.
- Barge-in: caller speech detected while a reply is playing cancels the outbound frame
  stream and sends Twilio a ``clear`` message, per requirements.md.

Assumption (undocumented upstream because the real TTS-producing agent is not this
feature's to write): ``emit_audio`` receives mono linear PCM16 at
``OPENAI_TTS_SAMPLE_RATE`` (default 24000 Hz, OpenAI TTS's native output rate). Flagged
in plan.md Integration deltas for confirmation against the real agent's TTS chunking.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Protocol, runtime_checkable

from app.phone.codec import (
    FRAME_MS,
    MULAW_FRAME_BYTES,
    MULAW_SAMPLE_RATE,
    chunk_bytes,
    encode_b64_frame,
    pcm16_to_mulaw,
    resample_pcm16,
)
from app.phone.latency import LatencyRecorder

DEFAULT_TTS_SAMPLE_RATE = int(os.environ.get("OPENAI_TTS_SAMPLE_RATE", "24000"))


@runtime_checkable
class TwilioSocket(Protocol):
    """The slice of a Starlette/FastAPI ``WebSocket`` the bridge needs -- narrowed so
    tests can pass a lightweight fake instead of a real socket."""

    async def send_json(self, data: dict) -> None: ...


@runtime_checkable
class TurnAgent(Protocol):
    """What the bridge needs from the turn-driver (``FakeAgent`` or, at integration, a
    thin adapter around the real ``AgentWorkflow`` -- see ``fake_agent.py``)."""

    async def handle_turn(self, text: str, bridge: object) -> None: ...


class TwilioMediaBridge:
    """One instance per live call. Implements ``app.contracts.SessionBridge``."""

    def __init__(
        self,
        socket: TwilioSocket,
        agent: TurnAgent,
        *,
        frame_interval_s: float = FRAME_MS / 1000,
        latency: LatencyRecorder | None = None,
    ) -> None:
        self._socket = socket
        self._agent = agent
        self._frame_interval_s = frame_interval_s
        self.latency = latency or LatencyRecorder()

        self.stream_sid: str | None = None
        self.transcript: list[tuple[str, str]] = []

        self._playback_task: asyncio.Task | None = None
        self._resample_state: object | None = None
        self._turn_start_ts: float | None = None

    def bind_stream(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid

    @property
    def is_playing(self) -> bool:
        return self._playback_task is not None and not self._playback_task.done()

    def mark_end_of_speech(self) -> None:
        """Call the moment VAD closes a turn -- the latency clock's t0."""
        self._turn_start_ts = time.monotonic()

    # -- app.contracts.SessionBridge ------------------------------------------------

    async def receive_user_utterance(self, text: str) -> None:
        await self.emit_transcript("user", text)
        await self._agent.handle_turn(text, self)

    async def emit_transcript(self, role: str, text: str) -> None:
        self.transcript.append((role, text))

    async def emit_audio(self, chunk: bytes, *, sample_rate: int | None = None) -> None:
        """Queue a TTS PCM16 chunk for playback, superseding any in-flight playback."""
        await self.interrupt_playback()
        rate = sample_rate or DEFAULT_TTS_SAMPLE_RATE
        self._playback_task = asyncio.create_task(self._play(chunk, rate))

    # -- barge-in --------------------------------------------------------------------

    async def interrupt_playback(self) -> None:
        """Cancel any in-flight outbound frames and tell Twilio to flush its jitter
        buffer. A true no-op (no ``clear`` sent) when nothing was actually playing --
        ``emit_audio`` calls this unconditionally before queuing new audio, and a
        routine turn-to-turn transition shouldn't spam Twilio with empty ``clear``s."""
        task, self._playback_task = self._playback_task, None
        if not (task and not task.done()):
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if self.stream_sid:
            await self._socket.send_json({"event": "clear", "streamSid": self.stream_sid})

    async def drain(self) -> None:
        """Wait for any in-flight playback to finish sending. Call when the call is
        ending (``stop``/disconnect) so a final reply isn't silently dropped mid-frame."""
        task = self._playback_task
        if task:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- internals ---------------------------------------------------------------

    async def _play(self, pcm16: bytes, sample_rate: int) -> None:
        pcm8k, self._resample_state = resample_pcm16(
            pcm16, sample_rate, MULAW_SAMPLE_RATE, self._resample_state
        )
        mulaw = pcm16_to_mulaw(pcm8k)
        frames = chunk_bytes(mulaw, MULAW_FRAME_BYTES)
        for frame in frames:
            await self._send_media_frame(frame)
            if self._frame_interval_s:
                await asyncio.sleep(self._frame_interval_s)

    async def _send_media_frame(self, mulaw_frame: bytes) -> None:
        if self._turn_start_ts is not None:
            self.latency.record(time.monotonic() - self._turn_start_ts)
            self._turn_start_ts = None
        await self._socket.send_json(
            {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": encode_b64_frame(mulaw_frame)},
            }
        )
