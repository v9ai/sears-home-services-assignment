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
    pipeline, context, _, _ = _build_conversation_pipeline(
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
    pipeline, _, _, _ = _build_conversation_pipeline(
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


async def test_multi_turn_recorder_aggregation():
    """Three turns through one pipeline: one sample per turn, percentiles over all."""
    session = VoiceSession.for_call("T-multi-turn")
    stt = FakeSTT(delay_s=0.03)
    llm = FakeLLM(delay_s=0.03)
    tts = FakeTTS(delay_s=0.03)
    pipeline, _, _, _ = _build_conversation_pipeline(
        session, stt, llm, tts, user_turn_strategies=_TEST_TURN_STRATEGIES
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    frames: list = []
    for _ in range(3):
        frames.extend(_turn_frames(stt_delay=0.03, tail_delay=0.03 + 0.03))
    await run_test(pipeline, frames_to_send=frames, observers=[observer])

    assert len(recorder.samples) == 3
    assert recorder.p50 > 0
    assert recorder.p95 >= recorder.p50
    assert recorder.within_budget() is True


async def test_mixed_over_under_budget_percentiles():
    """Per-call aggregation semantics: mostly-fast turns with one >4 s outlier must
    fail within_budget() via p95 while p50 stays under its budget — merged into one
    recorder exactly as production aggregates a call's turns."""
    recorder = LatencyRecorder()

    async def _drive(llm_delay: float, tail: float, call: str) -> None:
        session = VoiceSession.for_call(call)
        pipeline, _, _, _ = _build_conversation_pipeline(
            session,
            FakeSTT(delay_s=0.02),
            FakeLLM(delay_s=llm_delay),
            FakeTTS(delay_s=0.02),
            user_turn_strategies=_TEST_TURN_STRATEGIES,
        )
        observer = VoiceMetricsObserver(recorder)
        await run_test(
            pipeline,
            frames_to_send=_turn_frames(stt_delay=0.02, tail_delay=tail),
            observers=[observer],
        )

    for i in range(3):
        await _drive(0.05, 0.05 + 0.02, f"T-mixed-fast-{i}")
    await _drive(4.2, 4.2 + 0.02, "T-mixed-slow")

    assert len(recorder.samples) == 4
    assert recorder.p50 <= P50_BUDGET_S
    assert recorder.p95 > P95_BUDGET_S
    assert recorder.within_budget() is False


# Generous enough for CI jitter, tight enough that reintroduced serialization
# (e.g. an awaited persist or a re-serialized TTS handoff) blows the assertion.
_PIPELINE_OVERHEAD_ALLOWANCE_S = 0.35

# Stage delays for the attribution test: each case makes ONE stage dominant, proving
# the eos->first-audio window spans STT+LLM+TTS (no stage accidentally outside it).
_STAGE_CASES = {
    "stt-heavy": (0.4, 0.05, 0.05),
    "llm-heavy": (0.05, 0.4, 0.05),
    "tts-heavy": (0.05, 0.05, 0.4),
}


@pytest.mark.parametrize("case", sorted(_STAGE_CASES))
async def test_stage_dominant_delays_attribute_correctly(case):
    stt_d, llm_d, tts_d = _STAGE_CASES[case]
    session = VoiceSession.for_call(f"T-stage-{case}")
    pipeline, _, _, _ = _build_conversation_pipeline(
        session,
        FakeSTT(delay_s=stt_d),
        FakeLLM(delay_s=llm_d),
        FakeTTS(delay_s=tts_d),
        user_turn_strategies=_TEST_TURN_STRATEGIES,
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await run_test(
        pipeline,
        frames_to_send=_turn_frames(stt_delay=stt_d, tail_delay=llm_d + tts_d),
        observers=[observer],
    )

    assert len(recorder.samples) == 1
    sample = recorder.samples[0]
    # The timer runs from end-of-speech: STT's delay elapses before UserStoppedSpeaking
    # (FakeSTT reacts to UserStartedSpeaking; see module docstring), so the measured
    # window covers LLM + TTS, whichever is dominant, plus bounded pipeline overhead.
    floor = llm_d + tts_d
    assert sample >= floor * 0.9, f"{case}: sample {sample:.3f}s below its {floor:.3f}s floor"
    assert sample <= floor + _PIPELINE_OVERHEAD_ALLOWANCE_S, (
        f"{case}: overhead {sample - floor:.3f}s exceeds the "
        f"{_PIPELINE_OVERHEAD_ALLOWANCE_S:.2f}s allowance — serialization or an inline "
        "await crept into the Pipecat turn path"
    )


async def test_pipecat_overhead_floor():
    """The Pipecat analog of tests/latency/test_tts_pipeline.py::
    test_pipeline_overhead_floor — with pinned fake delays, eos->first-audio must land
    within (LLM + TTS) + a fixed overhead allowance."""
    session = VoiceSession.for_call("T-overhead-floor")
    pipeline, _, _, _ = _build_conversation_pipeline(
        session,
        FakeSTT(delay_s=0.10),
        FakeLLM(delay_s=0.20),
        FakeTTS(delay_s=0.10),
        user_turn_strategies=_TEST_TURN_STRATEGIES,
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    await run_test(
        pipeline,
        frames_to_send=_turn_frames(stt_delay=0.10, tail_delay=0.20 + 0.10),
        observers=[observer],
    )

    assert len(recorder.samples) == 1
    assert recorder.samples[0] <= 0.20 + 0.10 + _PIPELINE_OVERHEAD_ALLOWANCE_S


def test_budgets_unchanged():
    # Pin the constants this test's margins are built around — a change here should
    # force a look at this file's delay_s/SleepFrame margins, not silently drift.
    # Canonical source: app/latency/budgets.py (specs/latency/budgets.md).
    from app.latency.budgets import PHONE_E2E, WEB_E2E

    assert P50_BUDGET_S == PHONE_E2E.p50_s == 2.5
    assert P95_BUDGET_S == PHONE_E2E.p95_s == 4.0
    assert WEB_E2E.p50_s == 2.0
    assert WEB_E2E.p95_s == 3.5
