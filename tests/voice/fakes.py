"""Fake STT/LLM/TTS service doubles for hermetic voice-pipeline tests.

Each fake bypasses its base class's own `process_frame` (which drives real
provider-oriented machinery — audio buffering, text aggregation, audio contexts) in
favor of `FrameProcessor.process_frame` directly, so behavior is fully deterministic
and doesn't depend on undocumented base-class internals. Each still implements its
class's abstract `run_stt`/`run_tts` method (unused) to satisfy the ABC.

FakeSTT reacts to `UserStartedSpeakingFrame` (not `UserStoppedSpeakingFrame`) so its
transcript is guaranteed to have landed in the LLM context aggregator before the test
sends `UserStoppedSpeakingFrame` — Pipecat's `LLMUserAggregator`/turn-controller
dispatch is not strictly ordered when both frames are pushed back-to-back from within
one `process_frame` call, so tests must send `UserStartedSpeakingFrame`, wait out
`delay_s` via a `SleepFrame`, then send `UserStoppedSpeakingFrame` (see
`tests/voice/test_voice_latency_e2e.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService


class FakeSTT(STTService):
    """Ignores audio content; yields a fixed transcript `delay_s` after the user
    starts speaking (simulating streaming-STT processing latency)."""

    def __init__(self, *, text: str = "my dryer is loud", delay_s: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._delay_s = delay_s

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        return
        yield  # pragma: no cover — unused; process_frame is overridden directly

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await FrameProcessor.process_frame(self, frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            await self.push_frame(
                TranscriptionFrame(
                    text=self._text, user_id="caller", timestamp="2026-07-09T00:00:00Z"
                ),
                direction,
            )
        await self.push_frame(frame, direction)


class FakeLLM(LLMService):
    """Reacts to `LLMContextFrame`; pushes a canned reply `delay_s` after the turn's
    context is ready — mirrors `BaseOpenAILLMService.process_frame`'s own
    Start/Text/End sequencing, without a real network call."""

    def __init__(
        self,
        *,
        reply: str = "Sorry to hear that. Let's get it fixed.",
        delay_s: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._reply = reply
        self._delay_s = delay_s

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self.push_frame(LLMFullResponseStartFrame())
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            await self.push_frame(LLMTextFrame(text=self._reply))
            await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)


class FakeTTS(TTSService):
    """Ignores text content; yields one audio chunk `delay_s` after receiving text."""

    def __init__(self, *, delay_s: float = 0.0, sample_rate: int = 8000, **kwargs) -> None:
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._delay_s = delay_s

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        return
        yield  # pragma: no cover — unused; process_frame is overridden directly

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await FrameProcessor.process_frame(self, frame, direction)
        if isinstance(frame, TextFrame):
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            context_id = self.create_context_id()
            await self.push_frame(TTSStartedFrame(context_id=context_id))
            await self.push_frame(
                TTSAudioRawFrame(
                    audio=b"\x00\x00", sample_rate=self.sample_rate or 8000, num_channels=1
                )
            )
            await self.push_frame(TTSStoppedFrame(context_id=context_id))
        else:
            await self.push_frame(frame, direction)
