"""Codec round-trip + framing unit tests (validation.md "Codec round-trip").

Owned by telephony-twilio (COORDINATION.md §3: app/phone/). Placed under
``tests/phone/`` -- new files only, no edits to testing-evals' shared scaffolding
(``tests/conftest.py``) -- per this feature's plan.md Integration deltas note.
"""

import math
import struct

from app.phone.codec import (
    MULAW_FRAME_BYTES,
    MULAW_SAMPLE_RATE,
    chunk_bytes,
    decode_b64_frame,
    encode_b64_frame,
    mulaw_silence_frame,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    resample_pcm16,
)


def _sine_pcm16(
    freq_hz: float, sample_rate: int, duration_s: float, amplitude: int = 8000
) -> bytes:
    n = int(sample_rate * duration_s)
    samples = [int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def test_mulaw_pcm16_byte_stable_round_trip():
    """mu-law -> PCM16 -> mu-law is byte-stable (mu-law is inherently lossy once, but a
    second pass through the same codec must not drift further)."""
    pcm = _sine_pcm16(440, MULAW_SAMPLE_RATE, 0.5)
    mulaw_once = pcm16_to_mulaw(pcm)
    pcm_back = mulaw_to_pcm16(mulaw_once)
    mulaw_twice = pcm16_to_mulaw(pcm_back)
    assert mulaw_once == mulaw_twice


def test_pcm16_round_trip_is_close():
    pcm = _sine_pcm16(440, MULAW_SAMPLE_RATE, 0.1)
    recovered = mulaw_to_pcm16(pcm16_to_mulaw(pcm))
    assert len(recovered) == len(pcm)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    recovered_samples = struct.unpack(f"<{len(recovered) // 2}h", recovered)
    # mu-law is a lossy companding codec; bound the per-sample error generously.
    max_err = max(abs(a - b) for a, b in zip(samples, recovered_samples, strict=True))
    assert max_err < 1500


def test_b64_frame_round_trip():
    raw = mulaw_silence_frame()
    assert decode_b64_frame(encode_b64_frame(raw)) == raw


def test_mulaw_silence_decodes_to_near_zero_pcm():
    pcm = mulaw_to_pcm16(mulaw_silence_frame())
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    assert all(s == 0 for s in samples)


def test_chunk_bytes_exact_and_padded():
    data = b"x" * (MULAW_FRAME_BYTES * 3)
    frames = chunk_bytes(data, MULAW_FRAME_BYTES)
    assert len(frames) == 3
    assert all(len(f) == MULAW_FRAME_BYTES for f in frames)

    short = b"y" * (MULAW_FRAME_BYTES + 10)
    frames = chunk_bytes(short, MULAW_FRAME_BYTES)
    assert len(frames) == 2
    assert frames[1] == b"y" * 10 + b"\x00" * (MULAW_FRAME_BYTES - 10)


def test_resample_pcm16_changes_length_proportionally():
    pcm_24k = _sine_pcm16(440, 24000, 0.5)
    pcm_8k, _ = resample_pcm16(pcm_24k, 24000, 8000)
    # 24kHz -> 8kHz is a 3x downsample; allow audioop's small rounding slack.
    expected = len(pcm_24k) // 3
    assert abs(len(pcm_8k) - expected) <= 4 * 2  # a few samples' worth of bytes


def test_resample_noop_when_rates_match():
    pcm = _sine_pcm16(440, 8000, 0.05)
    out, state = resample_pcm16(pcm, 8000, 8000)
    assert out == pcm
    assert state is None
