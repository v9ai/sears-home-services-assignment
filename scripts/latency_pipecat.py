#!/usr/bin/env python3
"""Pipecat-native e2e latency bench (loop v2 q0-4).

Drives the PRODUCTION conversation pipeline (`app.voice.bot._build_conversation_pipeline`
— safety gate, prompt refresh, context aggregators, sanitizer) with the REAL LLM and
TTS services from the production factories (`_build_llm`/`_build_tts`, env-selected:
`VOICE_LLM_MODEL`, `TTS_PROVIDER`), measuring end-of-speech → first `TTSStartedFrame`
via the same `VoiceMetricsObserver` a live call uses. This closes v1's bench-fidelity
gap: `VOICE_LLM_MODEL`, TTS-provider flips, and the filler processor are now
bench-visible (`pipecat_eos_to_first_audio_ms` report rows).

STT is deliberately scripted (the scenario's caller line is injected as a
`TranscriptionFrame` on `UserStartedSpeakingFrame`, mirroring
`tests/voice/fakes.FakeSTT`) — real STT needs real caller audio, and its cost is
already measured by the `eos_to_stt_ms` micro row. The pipecat rows therefore cover
the LLM→TTS half of the phone envelope, timed by the production observer.

Not run at import time; `scripts/latency_bench.py` calls `bench_e2e_pipecat` inside
`_run_live` when the configured providers' keys are present (`needed_keys()`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Tail wait per turn: generous enough for a slow LLM+TTS round trip, bounded so a hung
# provider costs one turn, not the bench. A turn with no TTSStartedFrame inside this
# window yields no sample -> the summary's no-data handling fails it honestly.
TURN_TAIL_S = 12.0
# Gap between end-of-transcript and the stop-speaking frame (aggregation settle time).
TRANSCRIPT_SETTLE_S = 0.3


def needed_keys() -> list[str]:
    """Env keys the CONFIGURED pipecat providers require (bot.py factory defaults)."""
    needed: set[str] = set()
    llm_provider = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    needed.add("DEEPSEEK_API_KEY" if llm_provider == "deepseek" else "OPENAI_API_KEY")
    tts_provider = os.environ.get("TTS_PROVIDER", "cartesia").strip().lower()
    if tts_provider == "cartesia":
        needed.update(("CARTESIA_API_KEY", "CARTESIA_VOICE_ID"))
    elif tts_provider == "deepgram":
        needed.add("DEEPGRAM_API_KEY")
    else:
        needed.add("OPENAI_API_KEY")
    return sorted(k for k in needed if not os.environ.get(k))


def _make_scripted_stt(text: str):
    """An STTService that emits `text` as the transcript when the user starts
    speaking — same shape as tests/voice/fakes.FakeSTT (see module docstring there
    for the frame-ordering rationale)."""
    from pipecat.frames.frames import Frame, TranscriptionFrame, UserStartedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.services.stt_service import STTService

    class ScriptedSTT(STTService):
        async def run_stt(self, audio: bytes):
            return
            yield  # pragma: no cover — unused; process_frame is overridden directly

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await FrameProcessor.process_frame(self, frame, direction)
            if isinstance(frame, UserStartedSpeakingFrame):
                await self.push_frame(
                    TranscriptionFrame(
                        text=text, user_id="bench", timestamp="2026-01-01T00:00:00Z"
                    ),
                    direction,
                )
            await self.push_frame(frame, direction)

    return ScriptedSTT()


async def _drive_one_turn(caller_line: str, scenario_id: str, llm=None, tts=None) -> dict:  # noqa: ANN001
    from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test
    from pipecat.turns.user_start.external_user_turn_start_strategy import (
        ExternalUserTurnStartStrategy,
    )
    from pipecat.turns.user_stop.external_user_turn_stop_strategy import (
        ExternalUserTurnStopStrategy,
    )
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from app.phone.latency import LatencyRecorder
    from app.voice.bot import _build_conversation_pipeline, _build_llm, _build_tts
    from app.voice.metrics import VoiceMetricsObserver
    from app.voice.session import VoiceSession

    session = VoiceSession.for_call(f"bench-{scenario_id}")
    stt = _make_scripted_stt(caller_line)
    llm = llm or _build_llm()
    tts = tts or _build_tts()
    pipeline, _, _ = _build_conversation_pipeline(
        session,
        stt,
        llm,
        tts,
        user_turn_strategies=UserTurnStrategies(
            start=[ExternalUserTurnStartStrategy()],
            stop=[ExternalUserTurnStopStrategy(wait_for_transcript=True)],
        ),
    )
    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    # Module attribute (not the constant) so tests can monkeypatch the tail short.
    tail_s = sys.modules[__name__].TURN_TAIL_S
    await run_test(
        pipeline,
        frames_to_send=[
            UserStartedSpeakingFrame(),
            SleepFrame(sleep=TRANSCRIPT_SETTLE_S),
            UserStoppedSpeakingFrame(),
            SleepFrame(sleep=tail_s),
        ],
        observers=[observer],
    )

    sample_ms = recorder.samples[0] * 1000 if recorder.samples else None
    return {
        "channel": "pipecat",
        "scenario_id": scenario_id,
        "turn_index": 0,
        "pipecat_eos_to_first_audio_ms": sample_ms,
    }


async def bench_e2e_pipecat(
    scenarios: list[Any],
    m: int,
    llm=None,  # noqa: ANN001 — injection points for hermetic tests
    tts=None,  # noqa: ANN001
) -> list[dict]:
    """One scripted turn per scenario through the production Pipecat wiring.

    `llm`/`tts` are test-injection points (fakes); live runs leave them None so each
    turn constructs the REAL env-selected services — a fresh TTS websocket per turn,
    matching a fresh call's cost profile.
    """
    records: list[dict] = []
    for scenario in scenarios[:m]:
        records.append(
            await _drive_one_turn(scenario.turns[0].caller, scenario.id, llm=llm, tts=tts)
        )
    return records
