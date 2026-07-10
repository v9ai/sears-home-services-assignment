"""FillerProcessor behavior (latency-engineering perceived-first-audio bridge).

Drives the processor alone through `pipecat.tests.utils.run_test` — the filler logic
is pure frame bookkeeping (arm on turn end, cancel on speakable output / user resume,
once per turn), so no fake services are needed. Timings: the filler delay is pinned
short (0.1 s) and every SleepFrame leaves generous margin, mirroring the tolerance
style of tests/voice/test_voice_latency_e2e.py.
"""

from __future__ import annotations

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import (  # noqa: E402
    InterruptionFrame,
    TextFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.tests.utils import SleepFrame, run_test  # noqa: E402

from app.agent.fillers import PHONE_TOOL_FILLER  # noqa: E402
from app.voice.processors import FillerProcessor  # noqa: E402

_DELAY_S = 0.1
_PAST_DELAY = SleepFrame(sleep=_DELAY_S + 0.2)
_BEFORE_DELAY = SleepFrame(sleep=_DELAY_S / 2)


def _fillers(frames: list) -> list[TTSSpeakFrame]:
    return [f for f in frames if isinstance(f, TTSSpeakFrame)]


async def test_filler_fires_on_dead_air():
    processor = FillerProcessor(enabled=True, delay_s=_DELAY_S)
    down, _ = await run_test(
        processor,
        frames_to_send=[UserStoppedSpeakingFrame(), _PAST_DELAY],
    )
    fillers = _fillers(down)
    assert len(fillers) == 1
    assert fillers[0].text == PHONE_TOOL_FILLER


async def test_filler_suppressed_when_llm_is_fast():
    processor = FillerProcessor(enabled=True, delay_s=_DELAY_S)
    down, _ = await run_test(
        processor,
        frames_to_send=[
            UserStoppedSpeakingFrame(),
            _BEFORE_DELAY,
            TextFrame("Sounds like the drain pump."),  # LLM output beat the timer
            _PAST_DELAY,
        ],
    )
    assert _fillers(down) == []


async def test_filler_cancelled_when_caller_resumes():
    processor = FillerProcessor(enabled=True, delay_s=_DELAY_S)
    down, _ = await run_test(
        processor,
        frames_to_send=[
            UserStoppedSpeakingFrame(),
            _BEFORE_DELAY,
            UserStartedSpeakingFrame(),  # caller resumed mid-pause
            _PAST_DELAY,
        ],
    )
    assert _fillers(down) == []


async def test_filler_cancelled_on_interruption():
    processor = FillerProcessor(enabled=True, delay_s=_DELAY_S)
    down, _ = await run_test(
        processor,
        frames_to_send=[
            UserStoppedSpeakingFrame(),
            _BEFORE_DELAY,
            InterruptionFrame(),
            _PAST_DELAY,
        ],
    )
    assert _fillers(down) == []


async def test_filler_fires_at_most_once_per_turn_and_rearms_next_turn():
    processor = FillerProcessor(enabled=True, delay_s=_DELAY_S)
    down, _ = await run_test(
        processor,
        frames_to_send=[
            # Turn 1: fires once, and a duplicate stop frame must not re-fire it.
            UserStoppedSpeakingFrame(),
            _PAST_DELAY,
            UserStoppedSpeakingFrame(),
            _PAST_DELAY,
            # Turn 2: a new turn (user spoke again) gets a fresh once-per-turn budget.
            UserStartedSpeakingFrame(),
            UserStoppedSpeakingFrame(),
            _PAST_DELAY,
        ],
    )
    assert len(_fillers(down)) == 2


async def test_filler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FILLER_ENABLED", raising=False)
    processor = FillerProcessor(delay_s=_DELAY_S)  # enabled resolved from env: off
    down, _ = await run_test(
        processor,
        frames_to_send=[UserStoppedSpeakingFrame(), _PAST_DELAY],
    )
    assert _fillers(down) == []


async def test_filler_env_knobs(monkeypatch):
    monkeypatch.setenv("FILLER_ENABLED", "1")
    monkeypatch.setenv("FILLER_DELAY_MS", "100")
    processor = FillerProcessor()
    assert processor._enabled is True
    assert processor._delay_s == pytest.approx(0.1)
    down, _ = await run_test(
        processor,
        frames_to_send=[UserStoppedSpeakingFrame(), _PAST_DELAY],
    )
    assert len(_fillers(down)) == 1


async def test_filler_default_delay_is_the_perceived_budget(monkeypatch):
    """f6 (loop-v2 i11): with FILLER_DELAY_MS unset, the gate must equal
    FILLER_AFTER_EOS_MS — the old hardcoded 1000 ms default violated the very
    800 ms perceived-latency budget the filler exists to meet."""
    from app.latency.budgets import FILLER_AFTER_EOS_MS

    monkeypatch.delenv("FILLER_DELAY_MS", raising=False)
    monkeypatch.setenv("FILLER_ENABLED", "1")
    processor = FillerProcessor()
    assert processor._delay_s == pytest.approx(FILLER_AFTER_EOS_MS / 1000.0)
