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

from app.agent.trace import TurnTrace
from app.phone.codec import (
    FRAME_MS,
    MULAW_FRAME_BYTES,
    MULAW_SAMPLE_RATE,
    MULAW_SILENCE_BYTE,
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

    async def handle_turn(
        self,
        text: str,
        bridge: object,
        *,
        audio_seq: int | None = None,
        trace: TurnTrace | None = None,
    ) -> None: ...


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

        # Outbound TTS is a *stream*: the real agent calls ``emit_audio`` many times per
        # sentence (once per OpenAI TTS chunk). Those chunks must play back-to-back, so
        # they queue onto a single long-lived consumer rather than each superseding the
        # last. Barge-in (a genuine interruption) is the explicit ``interrupt_playback``
        # path, driven by caller speech in ``app/phone/routes.py`` -- not a side effect
        # of the next chunk arriving.
        self._queue: asyncio.Queue[tuple[bytes, int] | None] = asyncio.Queue()
        self._consumer: asyncio.Task | None = None
        self._playing = False
        self._resample_state: object | None = None
        self._pcm_carry = b""
        self._mulaw_carry = b""
        self._turn_start_ts: float | None = None
        self._turn_trace: TurnTrace | None = None

    def bind_stream(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid

    @property
    def is_playing(self) -> bool:
        return self._playing or not self._queue.empty()

    def mark_end_of_speech(self, trace: TurnTrace | None = None) -> None:
        """Call the moment VAD closes a turn -- the latency clock's t0."""
        self._turn_start_ts = time.monotonic()
        self._turn_trace = trace
        if trace is not None:
            trace.mark("t0", ts=self._turn_start_ts)

    # -- app.contracts.SessionBridge ------------------------------------------------

    async def receive_user_utterance(self, text: str, audio_seq: int | None = None) -> None:
        await self.emit_transcript("user", text)
        await self._agent.handle_turn(text, self, audio_seq=audio_seq, trace=self._turn_trace)

    async def emit_transcript(self, role: str, text: str) -> None:
        self.transcript.append((role, text))

    async def emit_audio(self, chunk: bytes, *, sample_rate: int | None = None) -> None:
        """Enqueue a TTS PCM16 chunk for sequential playback.

        Chunks stream out in order behind a single consumer -- consecutive chunks of the
        same reply do **not** interrupt each other. Use :meth:`interrupt_playback` for a
        real barge-in."""
        rate = sample_rate or DEFAULT_TTS_SAMPLE_RATE
        self._queue.put_nowait((chunk, rate))
        self._ensure_consumer()

    def _ensure_consumer(self) -> None:
        if self._consumer is None or self._consumer.done():
            self._consumer = asyncio.create_task(self._playback_loop())

    async def _playback_loop(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    await self._flush_tail()
                    return
                pcm16, sample_rate = item
                self._playing = True
                await self._play(pcm16, sample_rate)
            finally:
                self._playing = False
                self._queue.task_done()

    # -- barge-in --------------------------------------------------------------------

    async def interrupt_playback(self) -> None:
        """Flush all queued/in-flight outbound audio and tell Twilio to drop its jitter
        buffer (``clear``). A true no-op (no ``clear`` sent) when nothing was playing or
        queued -- a routine turn-to-turn transition shouldn't spam Twilio with empty
        ``clear``s; only a genuine barge-in over live audio sends one."""
        had_audio = self.is_playing
        consumer, self._consumer = self._consumer, None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._queue.task_done()
        if consumer is not None and not consumer.done():
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
        self._playing = False
        # A barge-in is a discontinuity: drop resample filter memory and any half-sample
        # / sub-frame carry so the next reply starts clean rather than resuming the
        # flushed stream.
        self._resample_state = None
        self._pcm_carry = b""
        self._mulaw_carry = b""
        if had_audio and self.stream_sid:
            await self._socket.send_json({"event": "clear", "streamSid": self.stream_sid})

    async def drain(self) -> None:
        """Play out everything queued, then stop the consumer. Call when the call is
        ending (``stop``/disconnect) so a final reply isn't silently dropped mid-frame."""
        consumer = self._consumer
        if consumer is None:
            return
        self._queue.put_nowait(None)
        self._consumer = None
        with contextlib.suppress(asyncio.CancelledError):
            await consumer

    # -- internals ---------------------------------------------------------------

    async def _play(self, pcm16: bytes, sample_rate: int) -> None:
        # Streamed PCM chunks can split on an odd byte boundary; audioop needs whole
        # 16-bit samples, so hold a trailing odd byte over to the next chunk.
        data = self._pcm_carry + pcm16
        if len(data) % 2:
            self._pcm_carry = data[-1:]
            data = data[:-1]
        else:
            self._pcm_carry = b""
        if data:
            pcm8k, self._resample_state = resample_pcm16(
                data, sample_rate, MULAW_SAMPLE_RATE, self._resample_state
            )
            self._mulaw_carry += pcm16_to_mulaw(pcm8k)
        await self._emit_whole_frames()

    async def _emit_whole_frames(self) -> None:
        """Send every complete 20 ms frame buffered so far, holding a sub-frame remainder
        for the next chunk -- so a small streamed chunk never gets padded with silence
        mid-reply (which would gap/inflate the audio)."""
        buf = self._mulaw_carry
        whole = len(buf) - (len(buf) % MULAW_FRAME_BYTES)
        self._mulaw_carry = buf[whole:]
        for i in range(0, whole, MULAW_FRAME_BYTES):
            await self._send_media_frame(buf[i : i + MULAW_FRAME_BYTES])
            if self._frame_interval_s:
                await asyncio.sleep(self._frame_interval_s)

    async def _flush_tail(self) -> None:
        """Emit the final sub-frame remainder (silence-padded to 20 ms) at end of call,
        so the last few ms of a reply aren't dropped."""
        if not self._mulaw_carry:
            return
        pad = MULAW_FRAME_BYTES - len(self._mulaw_carry)
        frame = self._mulaw_carry + MULAW_SILENCE_BYTE * pad
        self._mulaw_carry = b""
        await self._send_media_frame(frame)

    async def _send_media_frame(self, mulaw_frame: bytes) -> None:
        if self._turn_start_ts is not None:
            self.latency.record(time.monotonic() - self._turn_start_ts)
            self._turn_start_ts = None
        if self._turn_trace is not None:
            self._turn_trace.mark("first_audio")
            self._turn_trace = None
        await self._socket.send_json(
            {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": encode_b64_frame(mulaw_frame)},
            }
        )
