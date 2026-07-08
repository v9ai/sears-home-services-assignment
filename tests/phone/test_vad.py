"""VAD endpointing unit tests against fixture audio (validation.md).

"Fixture audio" here is synthesized in-process (a tone for speech, zeros for silence)
rather than checked-in binary fixtures -- deterministic, reviewable in the diff, and
exercises the same ``audioop.rms`` path real audio would.
"""

import math
import struct

from app.phone.vad import (
    DEFAULT_ENERGY_THRESHOLD,
    FRAME_MS,
    TurnSegmenter,
    frame_is_speech,
)

FRAME_SAMPLES = 8000 * FRAME_MS // 1000  # 160 samples/frame at 8kHz


def _tone_frame(amplitude: int = 12000, freq_hz: float = 300.0) -> bytes:
    samples = [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / 8000)) for i in range(FRAME_SAMPLES)
    ]
    return struct.pack(f"<{FRAME_SAMPLES}h", *samples)


def _silence_frame() -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES


def test_frame_is_speech_distinguishes_tone_from_silence():
    assert frame_is_speech(_tone_frame(), DEFAULT_ENERGY_THRESHOLD) is True
    assert frame_is_speech(_silence_frame(), DEFAULT_ENERGY_THRESHOLD) is False


def test_frame_is_speech_empty_frame_is_not_speech():
    assert frame_is_speech(b"") is False


def test_segmenter_silence_only_never_fires():
    seg = TurnSegmenter()
    for _ in range(50):
        assert seg.push(_silence_frame()) is None
    assert seg.is_speaking is False
    assert seg.flush() is None


def test_segmenter_fires_after_hangover():
    seg = TurnSegmenter(hangover_ms=300, frame_ms=FRAME_MS)
    # 5 frames (100ms) of speech.
    for _ in range(5):
        assert seg.push(_tone_frame()) is None
    assert seg.is_speaking is True

    # Hangover is 300ms == 15 frames of silence; the 15th should fire.
    turn = None
    for i in range(15):
        turn = seg.push(_silence_frame())
        if i < 14:
            assert turn is None
    assert turn is not None
    assert seg.is_speaking is False
    # Buffered turn includes the speech + trailing silence up to the hangover.
    assert len(turn) == (5 + 15) * FRAME_SAMPLES * 2


def test_segmenter_resets_after_firing():
    seg = TurnSegmenter(hangover_ms=40, frame_ms=FRAME_MS)  # 2 frames hangover
    for _ in range(3):
        seg.push(_tone_frame())
    for _ in range(2):
        turn = seg.push(_silence_frame())
    assert turn is not None

    # A second turn after the reset should segment independently.
    assert seg.push(_tone_frame()) is None
    assert seg.is_speaking is True
    turn2 = None
    for _ in range(2):
        turn2 = seg.push(_silence_frame())
    assert turn2 is not None
    assert turn2 != turn


def test_flush_force_closes_in_progress_turn():
    seg = TurnSegmenter()
    seg.push(_tone_frame())
    seg.push(_tone_frame())
    assert seg.is_speaking is True
    turn = seg.flush()
    assert turn is not None
    assert len(turn) == 2 * FRAME_SAMPLES * 2
    assert seg.is_speaking is False


def test_flush_with_no_speech_returns_none():
    seg = TurnSegmenter()
    assert seg.flush() is None
