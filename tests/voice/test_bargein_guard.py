"""Barge-in echo-guard tests (`app.voice.bot._build_user_turn_strategies`).

A PSTN call has no acoustic echo cancellation, so while the bot speaks its own TTS
returns on the inbound leg. Pipecat's default turn-start strategies interrupt on a
single raw VAD frame or any 1-word transcription — the returned echo fires
interruption → Twilio ``clear`` → the reply is flushed and restarts → stuttering
(docs/local-twilio-run.md "Stuttering during the reply"). The pre-port fix
(`app/phone/vad.py::BargeInDetector`) was deleted by the Pipecat port; the guard now
lives in `_build_user_turn_strategies` as a `MinWordsUserTurnStartStrategy`, tuned by
`VOICE_BARGEIN_MIN_WORDS` (0 = disabled, raw Pipecat defaults). These tests pin the
knob wiring and the behavior that makes the stutter impossible: short echo
transcriptions can't open a user turn while the bot is speaking.
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
from pipecat.turns.user_turn_strategies import UserTurnStrategies  # noqa: E402

from app.voice import bot as voice_bot  # noqa: E402
from app.voice.bot import (  # noqa: E402
    VOICE_BARGEIN_MIN_WORDS_DEFAULT,
    _build_conversation_pipeline,
    _build_user_turn_strategies,
)

# --- factory: the VOICE_BARGEIN_MIN_WORDS knob ---------------------------------------


def _start_strategy(strategies: UserTurnStrategies) -> MinWordsUserTurnStartStrategy:
    assert strategies is not None
    (start,) = strategies.start
    assert isinstance(start, MinWordsUserTurnStartStrategy)
    return start


def test_default_is_min_words_guard(monkeypatch):
    monkeypatch.delenv("VOICE_BARGEIN_MIN_WORDS", raising=False)
    start = _start_strategy(_build_user_turn_strategies())
    assert start._min_words == VOICE_BARGEIN_MIN_WORDS_DEFAULT
    assert start._use_interim is True  # interims trigger earlier, real barge-in stays snappy


def test_env_override_is_honored(monkeypatch):
    monkeypatch.setenv("VOICE_BARGEIN_MIN_WORDS", "5")
    start = _start_strategy(_build_user_turn_strategies())
    assert start._min_words == 5


def test_zero_disables_the_guard(monkeypatch):
    """The explicit rollback knob: 0 falls back to raw Pipecat default strategies."""
    monkeypatch.setenv("VOICE_BARGEIN_MIN_WORDS", "0")
    assert _build_user_turn_strategies() is None


def test_stop_strategies_stay_at_pipecat_defaults(monkeypatch):
    """The guard only changes turn START; end-of-turn detection is untouched."""
    monkeypatch.delenv("VOICE_BARGEIN_MIN_WORDS", raising=False)
    strategies = _build_user_turn_strategies()
    # UserTurnStrategies.__post_init__ fills stop with Pipecat's own defaults when the
    # factory leaves it unset — non-empty means defaults applied, none of ours.
    assert strategies.stop


# --- behavior: echo can't interrupt, callers still can --------------------------------


def _transcription(text: str, *, interim: bool = False):
    cls = InterimTranscriptionFrame if interim else TranscriptionFrame
    return cls(text=text, user_id="caller", timestamp="2026-07-09T00:00:00Z")


def _guard_with_recorder(monkeypatch) -> tuple[MinWordsUserTurnStartStrategy, list]:
    monkeypatch.delenv("VOICE_BARGEIN_MIN_WORDS", raising=False)
    strategy = _start_strategy(_build_user_turn_strategies())
    started: list = []

    async def _on_started(_strategy, params) -> None:
        started.append(params)

    strategy.add_event_handler("on_user_turn_started", _on_started)
    return strategy, started


async def test_echo_blips_cannot_interrupt_while_bot_speaks(monkeypatch):
    """The stutter scenario: bot speaking, echo comes back as short transcriptions
    (the documented hallucination shape: "Wow.", "watch.") — no turn may start."""
    strategy, started = _guard_with_recorder(monkeypatch)

    await strategy.process_frame(BotStartedSpeakingFrame())
    for echo in ("Wow.", "watch.", "thank you"):
        result = await strategy.process_frame(_transcription(echo, interim=True))
        assert result is not ProcessFrameResult.STOP
        result = await strategy.process_frame(_transcription(echo))
        assert result is not ProcessFrameResult.STOP

    assert started == []


async def test_real_barge_in_still_interrupts(monkeypatch):
    """A genuine talk-over (>= min_words words) must still open the turn."""
    strategy, started = _guard_with_recorder(monkeypatch)

    await strategy.process_frame(BotStartedSpeakingFrame())
    result = await strategy.process_frame(_transcription("wait stop I have a question"))

    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


async def test_single_word_opens_turn_when_bot_is_silent(monkeypatch):
    """Normal turn-taking is unchanged: with the bot quiet, one word suffices."""
    strategy, started = _guard_with_recorder(monkeypatch)

    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    result = await strategy.process_frame(_transcription("yes"))

    assert result is ProcessFrameResult.STOP
    assert len(started) == 1


# --- wiring: production pipeline uses the guard ---------------------------------------


def test_conversation_pipeline_uses_the_guard_by_default(monkeypatch):
    """`build_pipeline_task` passes no override, so `_build_conversation_pipeline`
    must consume the factory — otherwise the guard silently falls out of production
    (exactly how the port lost the original fix)."""
    from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS

    from app.voice.session import VoiceSession

    built: list = []
    real_factory = _build_user_turn_strategies

    def _recording_factory():
        strategies = real_factory()
        built.append(strategies)
        return strategies

    monkeypatch.setattr(voice_bot, "_build_user_turn_strategies", _recording_factory)
    session = VoiceSession.for_call("CA-bargein-test")
    _build_conversation_pipeline(session, FakeSTT(), FakeLLM(), FakeTTS())

    assert len(built) == 1
    assert built[0] is not None


def test_explicit_override_bypasses_the_factory(monkeypatch):
    """The test-only `user_turn_strategies` override keeps working unchanged."""
    from pipecat.turns.user_start import ExternalUserTurnStartStrategy
    from pipecat.turns.user_stop import ExternalUserTurnStopStrategy

    from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS

    from app.voice.session import VoiceSession

    monkeypatch.setattr(
        voice_bot,
        "_build_user_turn_strategies",
        lambda: pytest.fail("factory must not run when an override is passed"),
    )
    override = UserTurnStrategies(
        start=[ExternalUserTurnStartStrategy()],
        stop=[ExternalUserTurnStopStrategy(wait_for_transcript=True)],
    )
    session = VoiceSession.for_call("CA-bargein-test")
    _build_conversation_pipeline(
        session, FakeSTT(), FakeLLM(), FakeTTS(), user_turn_strategies=override
    )
