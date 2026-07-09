"""Guardrail parity: the voice channel's pre-LLM safety gate fires on exactly the scenarios
the web channel's gate does.

The voice `SafetyGateProcessor` reuses `app.agent.safety.detect_safety_trigger` verbatim
(`app/voice/processors.py`), so this asserts, over the whole scenario matrix, that the
detector flags exactly the scenarios whose `assert.safety_interrupt` is true — i.e. no
hazard scenario slips past the voice gate and no benign scenario trips it.
"""

from __future__ import annotations

import pytest

from app.agent.safety import detect_safety_trigger
from evals.scenarios.schema import load_scenarios

pytest.importorskip("pipecat.frames.frames")

_SCENARIOS = [s for s in load_scenarios() if not s.canary]


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
def test_voice_gate_fires_iff_scenario_expects_safety(scenario):
    caller_triggers = any(detect_safety_trigger(t.caller) is not None for t in scenario.turns)
    assert caller_triggers == scenario.assert_.safety_interrupt, (
        f"{scenario.id}: voice safety gate would "
        f"{'fire' if caller_triggers else 'NOT fire'} but scenario expects "
        f"safety_interrupt={scenario.assert_.safety_interrupt}"
    )


async def test_voice_gate_processor_matches_detector_end_to_end():
    """Spot-check that the processor (not just the detector) fires on a real hazard turn."""
    from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.tests.utils import run_test

    from app.agent.safety import SAFETY_RESPONSE
    from app.voice.processors import SafetyGateProcessor
    from app.voice.session import VoiceSession

    session = VoiceSession.for_call("T")
    gate = SafetyGateProcessor(session, LLMContext(messages=[{"role": "system", "content": "s"}]))
    down, _ = await run_test(
        gate,
        frames_to_send=[
            TranscriptionFrame(text="I smell gas", user_id="c", timestamp="2026-07-09T00:00:00Z")
        ],
        expected_down_frames=[TTSSpeakFrame],
    )
    assert any(isinstance(f, TTSSpeakFrame) and f.text == SAFETY_RESPONSE for f in down)
    assert session.case_file.safety_flag is True
