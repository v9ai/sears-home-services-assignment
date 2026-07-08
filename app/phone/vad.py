"""Server-side VAD (voice activity detection) for turn endpointing.

Energy (RMS)-based thresholding over 20 ms PCM16 frames -- no extra dependency beyond
the stdlib ``audioop`` codec already used for mu-law conversion (tech-stack.md forbids
adding new provider/vendor SDKs without declaring it; a WebRTC VAD binding is unneeded
weight for a turn-based, one-caller-at-a-time phone channel). This is deliberately
simple: it segments a call into caller turns for turn-based STT (requirements.md
Decision 3), it is not attempting far-field / multi-speaker robustness.

``TurnSegmenter`` is fed one inbound PCM16 frame at a time (post mu-law decode) and
fires with the buffered turn audio once speech is followed by ``hangover_ms`` of
silence (~300 ms per requirements.md).
"""

from __future__ import annotations

import audioop
import os
from dataclasses import dataclass, field

DEFAULT_ENERGY_THRESHOLD = 500
"""RMS threshold on 16-bit PCM samples; tuned generously above typical line-noise floor
and comfortably below a spoken voice at telephone gain -- adjust via constructor if a
live-call checklist run shows false triggers."""

# O7 (latency-engineering): env-tunable; default stays 300 ms. Lowering trades
# ~100 ms of turn latency against mid-utterance false cuts (see the spec's
# false-cut guard before changing it in production).
DEFAULT_HANGOVER_MS = int(os.environ.get("VAD_HANGOVER_MS", "300"))
FRAME_MS = 20


def frame_is_speech(pcm16_frame: bytes, threshold: int = DEFAULT_ENERGY_THRESHOLD) -> bool:
    """Whether one PCM16 frame's RMS energy clears the speech threshold."""
    if not pcm16_frame:
        return False
    return audioop.rms(pcm16_frame, 2) >= threshold


@dataclass
class TurnSegmenter:
    """Stateful turn endpointer: feed frames via :meth:`push`; get back the full turn's
    PCM16 bytes when speech ends (hangover elapses) or the call ends (:meth:`flush`)."""

    threshold: int = DEFAULT_ENERGY_THRESHOLD
    hangover_ms: int = DEFAULT_HANGOVER_MS
    frame_ms: int = FRAME_MS
    _speaking: bool = field(default=False, init=False, repr=False)
    _silence_ms: int = field(default=0, init=False, repr=False)
    _buffer: list[bytes] = field(default_factory=list, init=False, repr=False)

    @property
    def is_speaking(self) -> bool:
        """True while a turn is being buffered (used by the bridge for barge-in)."""
        return self._speaking

    def push(self, pcm16_frame: bytes) -> bytes | None:
        """Feed one 20 ms PCM16 frame. Returns the completed turn's PCM16 bytes once
        speech is followed by ``hangover_ms`` of silence; otherwise ``None``."""
        if frame_is_speech(pcm16_frame, self.threshold):
            self._speaking = True
            self._silence_ms = 0
            self._buffer.append(pcm16_frame)
            return None

        if not self._speaking:
            # Silence before any speech has started: nothing to buffer yet.
            return None

        self._silence_ms += self.frame_ms
        self._buffer.append(pcm16_frame)
        if self._silence_ms >= self.hangover_ms:
            return self._pop_turn()
        return None

    def flush(self) -> bytes | None:
        """Force-close whatever turn is in progress (e.g. on a Twilio ``stop`` event)."""
        if self._speaking and self._buffer:
            return self._pop_turn()
        self._reset()
        return None

    def _pop_turn(self) -> bytes:
        turn = b"".join(self._buffer)
        self._reset()
        return turn

    def _reset(self) -> None:
        self._speaking = False
        self._silence_ms = 0
        self._buffer = []
