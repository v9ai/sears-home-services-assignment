"""End-to-end latency test for the voice conversation pipeline (STT -> LLM -> TTS),
driven through `app.voice.bot._build_conversation_pipeline` with injected fake
services so it runs hermetically (no network, no API keys) while exercising the real
production wiring (safety gate, prompt refresh, context aggregators, sanitizer).

Turn detection: `LLMContextAggregatorPair`'s default turn strategies include a
smart-turn ML model that needs real audio to analyze, which a hermetic test can't
supply. `_build_conversation_pipeline`'s `user_turn_strategies` override lets tests
swap in `ExternalUserTurnStopStrategy`, which is driven directly by
`UserStartedSpeakingFrame`/`UserStoppedSpeakingFrame` — the same frames a VAD
processor would emit in production, just synthesized here.

Frame ordering: FakeSTT reacts to `UserStartedSpeakingFrame` (not
`UserStoppedSpeakingFrame`) precisely so the transcript has already landed in the
context aggregator by the time the test sends `UserStoppedSpeakingFrame` — see
`tests/voice/fakes.py` for why.
"""

from __future__ import annotations

import logging

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame  # noqa: E402
from pipecat.tests.utils import SleepFrame, run_test  # noqa: E402
from pipecat.turns.user_start.external_user_turn_start_strategy import (  # noqa: E402
    ExternalUserTurnStartStrategy,
)
from pipecat.turns.user_stop.external_user_turn_stop_strategy import (  # noqa: E402
    ExternalUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies  # noqa: E402

from app.phone.latency import P50_BUDGET_S, P95_BUDGET_S, LatencyRecorder  # noqa: E402
from app.voice.bot import _build_conversation_pipeline  # noqa: E402
from app.voice.metrics import VoiceMetricsObserver  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402

# Deterministic, event-driven turn detection for hermetic tests — production leaves
# this unset and gets Pipecat's own VAD + smart-turn defaults (see module docstring).
_TEST_TURN_STRATEGIES = UserTurnStrategies(
    start=[ExternalUserTurnStartStrategy()],
    stop=[ExternalUserTurnStopStrategy(wait_for_transcript=True)],
)


def _turn_frames(stt_delay: float, tail_delay: float) -> list:
    return [
        UserStartedSpeakingFrame(),
        SleepFrame(sleep=stt_delay + 0.1),  # let the transcript land before turn-stop
        UserStoppedSpeakingFrame(),
        SleepFrame(sleep=tail_delay + 0.3),
    ]


async def test_conversation_pipeline_latency_within_budget():
    session = VoiceSession.for_call("T-in-budget")
    stt = FakeSTT(delay_s=0.05)
    llm = FakeLLM(delay_s=0.05)
    tts = FakeTTS(delay_s=0.05)
    pipeline, context, _ = _build_conversation_pipeline(
        session, stt, llm, tts, user_turn_strategies=_TEST_TURN_STRATEGIES
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await run_test(
        pipeline,
        frames_to_send=_turn_frames(stt_delay=0.05, tail_delay=0.05 + 0.05),
        observers=[observer],
    )

    assert len(recorder.samples) == 1
    assert recorder.within_budget() is True
    assert recorder.samples[0] < P95_BUDGET_S
    assert any(m["role"] == "user" and "my dryer is loud" in m["content"] for m in context.messages)


async def test_conversation_pipeline_latency_over_budget_logs_warning(caplog):
    session = VoiceSession.for_call("T-over-budget")
    stt = FakeSTT(delay_s=0.02)
    llm = FakeLLM(delay_s=4.2)  # comfortably past P95_BUDGET_S=4.0 on its own
    tts = FakeTTS(delay_s=0.05)
    pipeline, _, _ = _build_conversation_pipeline(
        session, stt, llm, tts, user_turn_strategies=_TEST_TURN_STRATEGIES
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    with caplog.at_level(logging.INFO, logger="app.phone.latency"):
        await run_test(
            pipeline,
            frames_to_send=_turn_frames(stt_delay=0.02, tail_delay=4.2 + 0.05),
            observers=[observer],
        )

    assert len(recorder.samples) == 1
    assert recorder.samples[0] > P95_BUDGET_S
    assert recorder.within_budget() is False
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_budgets_unchanged():
    # Pin the constants this test's margins are built around — a change here should
    # force a look at this file's delay_s/SleepFrame margins, not silently drift.
    assert P50_BUDGET_S == 2.5
    assert P95_BUDGET_S == 4.0
