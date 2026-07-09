"""Pipecat voice pipeline (Twilio Media Streams) — the phone channel.

This package is the Pipecat port of the phone channel. It REPLACES the old hand-rolled
`app/phone` media bridge (µ-law codec, RMS VAD, batch STT, custom TTS queueing) with a
Pipecat pipeline: transport → STT → LLM → TTS. Crucially it does NOT re-implement any
business logic — every LlamaIndex tool, prompt, guardrail, and the knowledge base under
`app/agent`, `app/tools`, and `app/knowledge` is imported and reused verbatim:

    LlamaIndex `FunctionAgent` tool-calling loop  →  the Pipecat LLM service's own loop
    each LlamaIndex `FunctionTool`                →  a Pipecat `FunctionSchema` + handler
                                                     that calls the SAME `app.tools.*` fn
    `build_system_prompt(case_file)`             →  refreshed into the LLM context/turn
    `detect_safety_trigger` (pre-LLM guardrail)  →  `SafetyGateProcessor` after STT
    LlamaIndex `ChatMemoryBuffer` + `CaseFile`   →  Pipecat context aggregator + `VoiceSession`

See `app/voice/README.md` for the full inventory→mapping and run instructions.
"""

from __future__ import annotations

__all__ = ["run_bot", "VoiceSession"]


def __getattr__(name: str):  # lazy re-export so importing the package is cheap/pipecat-free
    if name == "run_bot":
        from app.voice.bot import run_bot

        return run_bot
    if name == "VoiceSession":
        from app.voice.session import VoiceSession

        return VoiceSession
    raise AttributeError(name)
