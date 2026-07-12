"""Structural guards for the answer->greeting perceived-latency budget
(`specs/latency/budgets.md`): the greeting is a constant spoken via `TTSSpeakFrame`
with NO LLM round trip in its path — the only hermetic guarantee possible for the
<= 1.5 s budget (a live number needs a real call; see the latency runbook).
"""

from __future__ import annotations

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import (  # noqa: E402
    LLMContextFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
)
from pipecat.tests.utils import run_test  # noqa: E402

from app.agent.prompts import GREETING  # noqa: E402
from app.voice.bot import _build_conversation_pipeline  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402


class CountingFakeLLM(FakeLLM):
    """FakeLLM that counts the turn contexts it is asked to complete."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.context_frames_seen = 0

    async def process_frame(self, frame, direction) -> None:  # noqa: ANN001
        if isinstance(frame, LLMContextFrame):
            self.context_frames_seen += 1
        await super().process_frame(frame, direction)


async def test_greeting_speaks_without_llm_roundtrip():
    """`TTSSpeakFrame(GREETING)` (what `on_client_connected` queues) must reach TTS
    and produce speech without EVER invoking the LLM — greeting cost = TTS only."""
    session = VoiceSession.for_call("T-greeting")
    llm = CountingFakeLLM(delay_s=0.0)
    pipeline, _, _, _ = _build_conversation_pipeline(
        session, FakeSTT(delay_s=0.0), llm, FakeTTS(delay_s=0.0)
    )

    frames_received, _ = await run_test(
        pipeline,
        frames_to_send=[TTSSpeakFrame(GREETING)],
    )

    assert any(isinstance(f, TTSStartedFrame) for f in frames_received), (
        "greeting never reached TTS — the answer->greeting budget has no path to hold"
    )
    assert llm.context_frames_seen == 0, (
        "the greeting triggered an LLM round trip — answer->greeting latency now "
        "includes LLM TTFT, breaking the <= 1.5 s perceived budget's structural basis"
    )


def test_greeting_budget_constants_referenced():
    # Keeps the perceived budgets from silently vanishing out of the central module.
    from app.latency.budgets import ANSWER_TO_GREETING_CACHED_MS, ANSWER_TO_GREETING_MS

    assert ANSWER_TO_GREETING_MS == 1500
    assert ANSWER_TO_GREETING_CACHED_MS == 500
