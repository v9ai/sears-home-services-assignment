"""mu-law <-> PCM16 codec and framing helpers for the Twilio Media Streams bridge.

Twilio Media Streams carry base64-encoded, single-channel, 8 kHz mu-law ("G.711 u-law")
audio in 20 ms frames (160 bytes of mu-law per frame). The rest of the pipeline (VAD,
OpenAI STT/TTS) operates on linear PCM16, so every inbound frame is decoded and every
outbound TTS chunk is resampled + re-encoded.

Uses the stdlib ``audioop`` module (deprecated since 3.11, removed in 3.13). Safe here
because the project pins Python 3.12 end to end (``pyproject.toml`` ``requires-python``,
root ``Dockerfile`` ``python:3.12-slim``); if the runtime ever moves to 3.13+, swap in
the drop-in ``audioop-lts`` backport package.
"""

from __future__ import annotations

import audioop  # stdlib, deprecated but present on the pinned 3.12 runtime (see docstring)
import base64

MULAW_SAMPLE_RATE = 8000
"""Sample rate Twilio Media Streams always use for mu-law payloads."""

FRAME_MS = 20
"""Twilio's fixed outbound framing granularity."""

MULAW_FRAME_BYTES = MULAW_SAMPLE_RATE * FRAME_MS // 1000
"""160 bytes: one mu-law byte per sample at 8 kHz, 20 ms of audio."""

PCM16_SAMPLE_WIDTH = 2

MULAW_SILENCE_BYTE = b"\xff"
"""mu-law encoding of a zero-amplitude PCM16 sample (verified against audioop below)."""


def mulaw_to_pcm16(mulaw: bytes) -> bytes:
    """Decode a mu-law byte string to linear PCM16 (same sample rate, mono)."""
    return audioop.ulaw2lin(mulaw, PCM16_SAMPLE_WIDTH)


def pcm16_to_mulaw(pcm16: bytes) -> bytes:
    """Encode linear PCM16 (mono) to mu-law."""
    return audioop.lin2ulaw(pcm16, PCM16_SAMPLE_WIDTH)


def decode_b64_frame(payload: str) -> bytes:
    """Decode a Twilio ``media.payload`` base64 string to raw mu-law bytes."""
    return base64.b64decode(payload)


def encode_b64_frame(data: bytes) -> str:
    """Encode raw bytes (mu-law) to the base64 string Twilio's ``media`` event expects."""
    return base64.b64encode(data).decode("ascii")


def resample_pcm16(
    pcm16: bytes, from_rate: int, to_rate: int, state: object | None = None
) -> tuple[bytes, object | None]:
    """Resample mono linear PCM16 between sample rates, threading ``audioop`` state
    across successive calls for a single stream (pass the returned state back in)."""
    if from_rate == to_rate:
        return pcm16, state
    converted, new_state = audioop.ratecv(pcm16, PCM16_SAMPLE_WIDTH, 1, from_rate, to_rate, state)
    return converted, new_state


def chunk_bytes(data: bytes, frame_size: int) -> list[bytes]:
    """Split ``data`` into ``frame_size``-byte frames, zero-padding a short final frame."""
    if frame_size <= 0:
        raise ValueError("frame_size must be positive")
    frames = []
    for i in range(0, len(data), frame_size):
        piece = data[i : i + frame_size]
        if len(piece) < frame_size:
            piece = piece + b"\x00" * (frame_size - len(piece))
        frames.append(piece)
    return frames


def mulaw_silence_frame() -> bytes:
    """One 20 ms frame of mu-law silence, e.g. to pad/prime an outbound stream."""
    return MULAW_SILENCE_BYTE * MULAW_FRAME_BYTES
