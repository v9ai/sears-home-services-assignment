"""Pipeline processors that port the agent's non-tool behavior into Pipecat.

Four small `FrameProcessor`s — three direct ports of existing mechanisms, one
perceived-latency bridge:

- `SafetyGateProcessor`  — the pre-LLM hazard interrupt (`app/agent/safety.py`), moved
  from `app/ws/routes.py`'s "check the raw utterance before the agent loop" into a
  processor placed right after STT, so it is still structurally impossible for the LLM to
  route around it.
- `SystemPromptRefreshProcessor` — replaces `app/agent/core.build_agent` rebuilding the
  system prompt from the live `CaseFile` every turn. Here we refresh the LLM context's
  system message in place at the start of each user turn (`build_system_prompt`), which is
  the never-re-ask mechanism.
- `SpokenTextSanitizer` — strips markdown/URLs from model text before TTS
  (`app/voice/text.sanitize_for_speech`); belt-and-suspenders over the voice-tuned prompt.
- `FillerProcessor` — speaks the shared tool-filler line when the LLM leaves the caller
  in dead air past `FILLER_DELAY_MS` (latency-engineering: perceived first-audio bridge).
"""

from __future__ import annotations

import asyncio
import logging
import os

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.agent.fillers import PHONE_TOOL_FILLER
from app.agent.prompts import build_system_prompt
from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
from app.obs import log_event
from app.voice.session import VoiceSession
from app.voice.text import sanitize_for_speech

logger = logging.getLogger("app.voice.processors")


class SafetyGateProcessor(FrameProcessor):
    """Pre-LLM safety interrupt (mission non-negotiable 1).

    Port of the gate in `app/ws/routes.py:_handle_user_text`: on a hazard match in the
    raw transcription, we set `safety_flag`, **swallow the transcription so the LLM never
    runs on it**, and speak the fixed `SAFETY_RESPONSE` directly via a `TTSSpeakFrame`.
    Both sides of the exchange are appended to the LLM context so history stays coherent
    and the safety-flag suffix (`build_system_prompt`) suppresses further DIY next turn.
    """

    def __init__(self, session: VoiceSession, context: LLMContext) -> None:
        super().__init__()
        self._session = session
        self._context = context

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            category = detect_safety_trigger(frame.text)  # same detector, unchanged
            if category is not None:
                logger.info(
                    "voice_safety_interrupt category=%s call=%s", category, self._session.call_sid
                )
                self._session.case_file.safety_flag = True
                self._context.add_message({"role": "user", "content": frame.text})
                self._context.add_message({"role": "assistant", "content": SAFETY_RESPONSE})
                await self.push_frame(TTSSpeakFrame(SAFETY_RESPONSE), FrameDirection.DOWNSTREAM)
                return  # swallow: the transcription never reaches the LLM aggregator

        await self.push_frame(frame, direction)


class SystemPromptRefreshProcessor(FrameProcessor):
    """Refresh the LLM context's system message from the live `CaseFile` each user turn.

    Equivalent to `app/agent/core.build_agent` rebuilding `system_prompt=build_system_prompt
    (case_file)` per turn: the compact `CaseFile` JSON (+ safety suffix) is re-injected so
    the model is always told, in the system prompt, everything it must not re-ask.
    Placed after the safety gate, so safety-interrupt turns (transcription swallowed) don't
    trigger a refresh or an LLM run.
    """

    def __init__(self, session: VoiceSession, context: LLMContext) -> None:
        super().__init__()
        self._session = session
        self._context = context

    def refresh(self) -> None:
        prompt = build_system_prompt(self._session.case_file)
        messages = self._context.messages
        if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
            messages[0]["content"] = prompt
        else:
            messages.insert(0, {"role": "system", "content": prompt})

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text:
            self.refresh()
        await self.push_frame(frame, direction)


def _filler_enabled_default() -> bool:
    return os.environ.get("FILLER_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _filler_delay_default_s() -> float:
    # Default derives from the perceived-latency budget itself (loop-v2 i11/f6): the
    # old hardcoded 1000 ms default violated FILLER_AFTER_EOS_MS=800 — the filler's
    # whole job is to land within that budget when the reply hasn't.
    from app.latency.budgets import FILLER_AFTER_EOS_MS

    return float(os.environ.get("FILLER_DELAY_MS", str(FILLER_AFTER_EOS_MS))) / 1000.0


class FillerProcessor(FrameProcessor):
    """Bridge dead air with the shared tool-filler line (perceived-latency fix).

    Sits between the LLM and the sanitizer. Arms on `UserStoppedSpeakingFrame`; if no
    speakable output (an LLM `TextFrame`, or a `TTSSpeakFrame` such as the safety line)
    has passed downstream within `delay_s`, pushes `PHONE_TOOL_FILLER` as a
    `TTSSpeakFrame` so TTS covers the remaining LLM/tool-loop wait. Fires at most once
    per turn; the caller resuming (`UserStartedSpeakingFrame`) or an `InterruptionFrame`
    cancels a pending filler and resets the once-per-turn budget.

    Off unless FILLER_ENABLED is truthy: the hermetic latency tests drive
    `_build_conversation_pipeline` with slow fakes and assert on eos->first-audio, which
    a filler would short-circuit — production opts in via .env. When a filler fires,
    `voice.metrics.latency` records *perceived* first audio for that turn; the
    `voice.filler.played` event keeps the real LLM/TTS gap diagnosable.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        delay_s: float | None = None,
        phrase: str = PHONE_TOOL_FILLER,
    ) -> None:
        super().__init__()
        self._enabled = _filler_enabled_default() if enabled is None else enabled
        self._delay_s = _filler_delay_default_s() if delay_s is None else delay_s
        self._phrase = phrase
        self._timer: asyncio.Task | None = None
        self._fired_this_turn = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (UserStartedSpeakingFrame, InterruptionFrame)):
            # The caller is speaking again (or barged in): a pending filler is stale, and
            # the once-per-turn budget resets for the turn now starting.
            await self._disarm()
            self._fired_this_turn = False
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._arm()
        elif isinstance(frame, (TextFrame, TTSSpeakFrame)):
            # Speakable output is on its way to TTS — the dead-air window is over.
            await self._disarm()

        await self.push_frame(frame, direction)

    def _arm(self) -> None:
        if not self._enabled or self._fired_this_turn or self._timer is not None:
            return
        self._timer = self.create_task(self._fire_after_delay())

    async def _disarm(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            await self.cancel_task(timer)

    async def _fire_after_delay(self) -> None:
        await asyncio.sleep(self._delay_s)
        self._timer = None
        self._fired_this_turn = True
        log_event(logger, "voice.filler.played", delay_ms=self._delay_s * 1000)
        await self.push_frame(TTSSpeakFrame(self._phrase), FrameDirection.DOWNSTREAM)

    async def cleanup(self) -> None:
        await self._disarm()
        await super().cleanup()


class SpokenTextSanitizer(FrameProcessor):
    """Strip markdown/URLs from model text on its way to TTS (voice output hygiene).

    The LLM streams `TextFrame`s (and `LLMTextFrame`, a subclass) token-by-token; we scrub
    each with `sanitize_for_speech`. Also scrubs any `TTSSpeakFrame` (e.g. the safety line)
    for consistency. Sits between the LLM and TTS.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            cleaned = sanitize_for_speech(frame.text)
            if cleaned != frame.text:
                frame.text = cleaned
        elif isinstance(frame, TTSSpeakFrame):
            cleaned = sanitize_for_speech(frame.text)
            if cleaned != frame.text:
                frame.text = cleaned

        await self.push_frame(frame, direction)
