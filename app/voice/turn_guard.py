"""Echo-tail turn-start guard (stutter-loop f1).

`MinWordsUserTurnStartStrategy` drops its word bar to 1 the INSTANT the bot stops
speaking — but on an AEC-less PSTN leg the bot's last words are still in flight to
the caller and echo back ~a few hundred ms AFTER `BotStoppedSpeakingFrame`. That
trailing echo transcribes as a short fragment ("Wow.", "watch.") and opened a phantom
caller turn (the second documented incident, docs/local-twilio-run.md "Agent replying
to phantom turns"; measured by the stutter bench's `phantom_tail` probe).

`EchoTailMinWordsStrategy` keeps requiring `min_words` for `tail_s` after the bot
stops. Within the tail a GENUINE utterance (>= min_words) still opens the turn
immediately — the guard filters short fragments only, so a caller's quick real answer
is never lost, and a quick one-word "yes" lands fine once the tail (default 400 ms)
has passed.

Coupling note: this subclass reaches into pipecat's `_bot_speaking` /
`_handle_transcription` internals (no public extension point in 1.5.0).
`tests/voice/test_echo_tail_guard.py` pins that contract so a pipecat upgrade that
breaks it fails loudly.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)


class EchoTailMinWordsStrategy(MinWordsUserTurnStartStrategy):
    """Min-words turn start whose word bar survives `tail_s` past bot speech."""

    def __init__(
        self,
        *,
        min_words: int,
        tail_s: float,
        clock: Callable[[], float] = time.monotonic,
        **kwargs,
    ) -> None:
        super().__init__(min_words=min_words, **kwargs)
        self._tail_s = tail_s
        self._clock = clock
        self._bot_stopped_at: float | None = None

    async def reset(self) -> None:
        await super().reset()
        self._bot_stopped_at = None

    def _in_echo_tail(self) -> bool:
        return (
            self._bot_stopped_at is not None
            and (self._clock() - self._bot_stopped_at) < self._tail_s
        )

    async def process_frame(self, frame) -> ProcessFrameResult:
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_stopped_at = None
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_stopped_at = self._clock()
        elif (
            isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
            and not self._bot_speaking
            and self._in_echo_tail()
        ):
            # Trailing echo window: hold the min-words bar as if the bot were still
            # speaking, so the parent's word-count logic applies unchanged.
            self._bot_speaking = True
            try:
                return await super().process_frame(frame)
            finally:
                self._bot_speaking = False
        return await super().process_frame(frame)
