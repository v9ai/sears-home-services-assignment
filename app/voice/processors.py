"""Pipeline processors that port the agent's non-tool behavior into Pipecat.

Three small `FrameProcessor`s, each a direct port of an existing mechanism:

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
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.agent.prompts import build_system_prompt
from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
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
