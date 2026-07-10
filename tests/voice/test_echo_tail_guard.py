"""Echo-tail guard tests (stutter-loop f1, `app/voice/turn_guard.py`).

Plain MinWords drops its word bar to 1 the instant the bot stops speaking, but on an
AEC-less PSTN leg the bot's LAST words echo back a few hundred ms AFTER
`BotStoppedSpeakingFrame` — the phantom-turn incident (docs/local-twilio-run.md
"Agent replying to phantom turns"; bench measured tail_echo_turns_opened=1 before
f1). `EchoTailMinWordsStrategy` holds the bar for `VOICE_BARGEIN_TAIL_MS` past bot
speech. These tests drive it with an injectable fake clock; the factory tests pin the
production wiring and the rollback knob.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat.turns.user_start.min_words_user_turn_start_strategy")

from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.turns.types import ProcessFrameResult  # noqa: E402
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (  # noqa: E402
    MinWordsUserTurnStartStrategy,
)

from app.voice.bot import (  # noqa: E402
    VOICE_BARGEIN_TAIL_MS_DEFAULT,
    _build_user_turn_strategies,
)
from app.voice.turn_guard import EchoTailMinWordsStrategy  # noqa: E402

TS = "2026-07-10T00:00:00Z"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _transcription(text: str, *, interim: bool = False):
    cls = InterimTranscriptionFrame if interim else TranscriptionFrame
    return cls(text=text, user_id="caller", timestamp=TS)


def _guard(
    min_words: int = 3, tail_s: float = 0.4
) -> tuple[EchoTailMinWordsStrategy, FakeClock, list]:
    clock = FakeClock()
    strategy = EchoTailMinWordsStrategy(
        min_words=min_words, tail_s=tail_s, clock=clock, use_interim=True
    )
    started: list = []

    async def _on_started(_strategy, params) -> None:
        started.append(params)

    strategy.add_event_handler("on_user_turn_started", _on_started)
    return strategy, clock, started


# --- tail behavior -------------------------------------------------------------------


async def test_tail_echo_fragment_does_not_open_a_turn():
    """The f1 scenario: bot stops, 100 ms later its own last word echoes back."""
    strategy, clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.1)

    result = await strategy.process_frame(_transcription("Wow."))

    assert result is not ProcessFrameResult.STOP
    assert started == []


async def test_tail_echo_interim_fragment_also_guarded():
    strategy, clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.2)

    await strategy.process_frame(_transcription("watch.", interim=True))

    assert started == []


async def test_genuine_answer_inside_tail_opens_turn():
    """Anti-overcorrection: the tail holds the WORD BAR, it does not mute — a real
    >= min_words utterance inside the window still opens the turn immediately."""
    strategy, clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.1)

    result = await strategy.process_frame(_transcription("yes tomorrow morning works fine"))

    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


async def test_one_word_answer_after_tail_opens_turn():
    """The caller's quick 'yes' lands once the echo window has passed."""
    strategy, clock, started = _guard(tail_s=0.4)
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.5)

    result = await strategy.process_frame(_transcription("yes"))

    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


async def test_bot_restarting_speech_clears_the_tail():
    """A new bot utterance supersedes the old tail: while speaking, min_words applies
    (inherited), and the tail re-arms from the NEW stop."""
    strategy, clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.1)
    await strategy.process_frame(BotStartedSpeakingFrame())  # bot speaks again

    await strategy.process_frame(_transcription("Wow."))  # while speaking: min_words
    assert started == []

    await strategy.process_frame(BotStoppedSpeakingFrame())
    clock.advance(0.5)  # past the NEW tail
    await strategy.process_frame(_transcription("yes"))
    assert len(started) == 1


async def test_reset_clears_tail_state():
    strategy, clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    await strategy.reset()
    clock.advance(0.1)

    # After reset there is no tail (and no bot speech): one word opens the turn.
    result = await strategy.process_frame(_transcription("yes"))
    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


async def test_while_bot_speaks_min_words_still_applies():
    """Inherited barge-in behavior is untouched by the subclass."""
    strategy, _clock, started = _guard()
    await strategy.process_frame(BotStartedSpeakingFrame())

    await strategy.process_frame(_transcription("thank you"))
    assert started == []
    result = await strategy.process_frame(_transcription("wait stop I have a question"))
    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


# --- factory wiring ------------------------------------------------------------------


def _start_strategy(strategies):
    assert strategies is not None
    (start,) = strategies.start
    return start


def test_factory_builds_echo_tail_guard_by_default(monkeypatch):
    monkeypatch.delenv("VOICE_BARGEIN_MIN_WORDS", raising=False)
    monkeypatch.delenv("VOICE_BARGEIN_TAIL_MS", raising=False)
    start = _start_strategy(_build_user_turn_strategies())
    assert isinstance(start, EchoTailMinWordsStrategy)
    assert start._tail_s == pytest.approx(VOICE_BARGEIN_TAIL_MS_DEFAULT / 1000)
    assert start._min_words == 3


def test_factory_tail_env_override(monkeypatch):
    monkeypatch.setenv("VOICE_BARGEIN_TAIL_MS", "250")
    start = _start_strategy(_build_user_turn_strategies())
    assert isinstance(start, EchoTailMinWordsStrategy)
    assert start._tail_s == pytest.approx(0.25)


def test_factory_tail_zero_reverts_to_plain_min_words(monkeypatch):
    """The f1 rollback knob: tail off, min-words guard stays."""
    monkeypatch.setenv("VOICE_BARGEIN_TAIL_MS", "0")
    start = _start_strategy(_build_user_turn_strategies())
    assert type(start) is MinWordsUserTurnStartStrategy
    assert start._min_words == 3
