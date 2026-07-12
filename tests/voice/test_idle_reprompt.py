"""Dead-air recovery: the idle policy (app/voice/idle.py) and its bot wiring.

Live-call gap this guards (evaluator-team finding, 2026-07-12): before this, a
silent caller heard nothing forever — no reprompt existed anywhere in `app/`.
The escalation ladder is unit-tested here; the pipeline wiring is asserted
structurally (the user aggregator really carries the env-configured
`user_idle_timeout`), not by driving real multi-second timeouts through
`run_test` — the controller itself (timer starts when the bot stops speaking,
cancels when the caller starts) is Pipecat's own tested `UserIdleController`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat.frames.frames")

from pipecat.turns.user_start.external_user_turn_start_strategy import (  # noqa: E402
    ExternalUserTurnStartStrategy,
)
from pipecat.turns.user_stop.external_user_turn_stop_strategy import (  # noqa: E402
    ExternalUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies  # noqa: E402

from app.voice.bot import _build_conversation_pipeline  # noqa: E402
from app.voice.idle import (  # noqa: E402
    VOICE_IDLE_MAX_REPROMPTS_DEFAULT,
    VOICE_IDLE_REPROMPT_SECS_DEFAULT,
    IdleRepromptPolicy,
    idle_max_reprompts,
    idle_reprompt_secs,
)
from app.voice.session import VoiceSession  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402

_TEST_TURN_STRATEGIES = UserTurnStrategies(
    start=[ExternalUserTurnStartStrategy()],
    stop=[ExternalUserTurnStopStrategy(wait_for_transcript=True)],
)


def _build(session_id: str):
    return _build_conversation_pipeline(
        VoiceSession.for_call(session_id),
        FakeSTT(delay_s=0.0),
        FakeLLM(delay_s=0.0),
        FakeTTS(delay_s=0.0),
        user_turn_strategies=_TEST_TURN_STRATEGIES,
    )


def test_policy_escalates_reprompt_reprompt_goodbye():
    policy = IdleRepromptPolicy(max_reprompts=2)
    assert policy.next_action() == "reprompt"
    assert policy.next_action() == "reprompt"
    assert policy.next_action() == "goodbye"


def test_policy_reset_on_user_speech_restarts_the_ladder():
    # Only CONSECUTIVE silences may escalate: a caller who answers a reprompt and
    # goes quiet again later starts a fresh ladder, never an instant goodbye.
    policy = IdleRepromptPolicy(max_reprompts=1)
    assert policy.next_action() == "reprompt"
    policy.reset()
    assert policy.next_action() == "reprompt"
    assert policy.next_action() == "goodbye"


def test_env_defaults_overrides_and_garbage(monkeypatch):
    monkeypatch.delenv("VOICE_IDLE_REPROMPT_SECS", raising=False)
    monkeypatch.delenv("VOICE_IDLE_MAX_REPROMPTS", raising=False)
    assert idle_reprompt_secs() == VOICE_IDLE_REPROMPT_SECS_DEFAULT
    assert idle_max_reprompts() == VOICE_IDLE_MAX_REPROMPTS_DEFAULT

    monkeypatch.setenv("VOICE_IDLE_REPROMPT_SECS", "7.5")
    monkeypatch.setenv("VOICE_IDLE_MAX_REPROMPTS", "1")
    assert idle_reprompt_secs() == 7.5
    assert idle_max_reprompts() == 1

    # Garbage falls back to the default rather than crashing call setup.
    monkeypatch.setenv("VOICE_IDLE_REPROMPT_SECS", "soon-ish")
    assert idle_reprompt_secs() == VOICE_IDLE_REPROMPT_SECS_DEFAULT


def test_conversation_pipeline_arms_the_idle_timer(monkeypatch):
    monkeypatch.setenv("VOICE_IDLE_REPROMPT_SECS", "9")
    _pipeline, _context, _refresh, aggregators = _build("T-idle-armed")
    assert aggregators.user()._params.user_idle_timeout == 9.0


def test_idle_timer_disabled_at_zero(monkeypatch):
    # 0 must mean OFF end-to-end: the params keep pipecat's 0 default, under which
    # UserIdleController never starts a timer.
    monkeypatch.setenv("VOICE_IDLE_REPROMPT_SECS", "0")
    _pipeline, _context, _refresh, aggregators = _build("T-idle-off")
    assert aggregators.user()._params.user_idle_timeout == 0
