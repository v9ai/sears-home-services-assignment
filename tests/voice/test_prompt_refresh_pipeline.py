"""Frame-driven prompt-refresh + gate-ordering guarantees (bugfix-loop T6).

`SystemPromptRefreshProcessor.refresh()` was only ever called directly in
tests; the frame dispatch (refresh on non-empty TranscriptionFrame, and only
then), the insert-branch when the context head isn't a system message, and the
documented "safety-swallowed turns don't refresh or reach the LLM" ordering
had no assertions — a regression in any of them would have shipped silently.
"""

from __future__ import annotations

import pytest

from app.agent.safety import SAFETY_RESPONSE
from app.voice.processors import SafetyGateProcessor, SystemPromptRefreshProcessor
from app.voice.session import VoiceSession

pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import TextFrame, TranscriptionFrame, TTSSpeakFrame  # noqa: E402
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.tests.utils import run_test  # noqa: E402

PLACEHOLDER = "placeholder-system-prompt"


def _transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="2026-07-10T00:00:00Z")


def _session_with_facts() -> VoiceSession:
    session = VoiceSession.for_call("T6")
    session.case_file.appliance_type = "dishwasher"
    session.case_file.brand = "Bosch"
    return session


async def test_transcription_frame_triggers_refresh_through_the_pipeline() -> None:
    session = _session_with_facts()
    context = LLMContext(messages=[{"role": "system", "content": PLACEHOLDER}])
    down, _ = await run_test(
        SystemPromptRefreshProcessor(session, context),
        frames_to_send=[_transcription("it leaks at the door")],
        expected_down_frames=[TranscriptionFrame],
    )
    system = context.messages[0]
    assert system["role"] == "system"
    assert "dishwasher" in system["content"] and "Bosch" in system["content"]
    assert any(isinstance(f, TranscriptionFrame) for f in down), "utterance must still flow on"


@pytest.mark.parametrize(
    "frame",
    [TextFrame(text="assistant text, not a user turn"), _transcription("")],
    ids=["non-transcription", "empty-text"],
)
async def test_other_frames_do_not_refresh(frame) -> None:
    session = _session_with_facts()
    context = LLMContext(messages=[{"role": "system", "content": PLACEHOLDER}])
    await run_test(
        SystemPromptRefreshProcessor(session, context),
        frames_to_send=[frame],
        expected_down_frames=[type(frame)],
    )
    assert context.messages[0]["content"] == PLACEHOLDER


@pytest.mark.parametrize(
    "initial",
    [[], [{"role": "user", "content": "hi"}]],
    ids=["empty-context", "head-not-system"],
)
async def test_refresh_prepends_system_when_head_is_not_system(initial) -> None:
    session = _session_with_facts()
    context = LLMContext(messages=list(initial))
    await run_test(
        SystemPromptRefreshProcessor(session, context),
        frames_to_send=[_transcription("hello")],
        expected_down_frames=[TranscriptionFrame],
    )
    assert context.messages[0]["role"] == "system"
    assert "dishwasher" in context.messages[0]["content"]
    # Pre-existing conversation is preserved behind the inserted prompt.
    assert [m["role"] for m in context.messages[1:]] == [m["role"] for m in initial]


async def test_safety_swallowed_turn_skips_refresh_and_never_reaches_the_llm() -> None:
    # The documented ordering guarantee: gate BEFORE refresher, so a hazard
    # turn neither refreshes the prompt nor flows toward the LLM aggregator.
    session = _session_with_facts()
    context = LLMContext(messages=[{"role": "system", "content": PLACEHOLDER}])
    gate = SafetyGateProcessor(session, context)
    refresher = SystemPromptRefreshProcessor(session, context)
    down, _ = await run_test(
        Pipeline([gate, refresher]),
        frames_to_send=[_transcription("I smell gas near the oven")],
        expected_down_frames=[TTSSpeakFrame],
    )
    assert session.case_file.safety_flag is True
    assert any(isinstance(f, TTSSpeakFrame) and f.text == SAFETY_RESPONSE for f in down)
    assert not any(isinstance(f, TranscriptionFrame) for f in down)
    assert context.messages[0]["content"] == PLACEHOLDER, (
        "swallowed turn must not refresh the system prompt"
    )
    # Both sides of the safety exchange are still recorded for history coherence.
    roles = [m["role"] for m in context.messages]
    assert roles.count("user") == 1 and roles.count("assistant") == 1


async def test_normal_turn_through_the_gate_still_refreshes() -> None:
    session = _session_with_facts()
    context = LLMContext(messages=[{"role": "system", "content": PLACEHOLDER}])
    down, _ = await run_test(
        Pipeline(
            [SafetyGateProcessor(session, context), SystemPromptRefreshProcessor(session, context)]
        ),
        frames_to_send=[_transcription("my dishwasher leaks at the door")],
        expected_down_frames=[TranscriptionFrame],
    )
    assert "dishwasher" in context.messages[0]["content"]
    assert any(isinstance(f, TranscriptionFrame) for f in down)
    assert session.case_file.safety_flag is False
