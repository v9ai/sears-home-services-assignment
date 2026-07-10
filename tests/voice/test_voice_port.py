"""Tests for the Pipecat voice port (`app/voice`).

Covers the port's structural guarantees without a live call: tool parity with the original
LlamaIndex tools, the pre-LLM safety gate, the never-re-ask system-prompt refresh, spoken
hygiene, and session-id stability. Requires `pipecat-ai` (a project dependency).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.safety import SAFETY_RESPONSE
from app.tools import core_tools
from app.voice.processors import (
    SafetyGateProcessor,
    SpokenTextSanitizer,
    SystemPromptRefreshProcessor,
)
from app.voice.session import VoiceSession
from app.voice.text import sanitize_for_speech
from app.voice.tools import build_tools

pipecat_frames = pytest.importorskip("pipecat.frames.frames")
from pipecat.frames.frames import TextFrame, TranscriptionFrame, TTSSpeakFrame  # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.tests.utils import run_test  # noqa: E402


async def _drive(handler, arguments: dict) -> str:
    captured: list[str] = []

    async def result_callback(result, **_kwargs):
        captured.append(result)

    await handler(SimpleNamespace(arguments=arguments, result_callback=result_callback))
    return captured[0]


def _transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="2026-07-09T00:00:00Z")


@pytest.mark.parametrize(
    "tool_name,args,origin,origin_kwargs",
    [
        (
            "identify_appliance",
            {"appliance_type": "washer"},
            core_tools.identify_appliance,
            {"appliance_type": "washer"},
        ),
        (
            "identify_appliance",
            {"appliance_type": "blender"},
            core_tools.identify_appliance,
            {"appliance_type": "blender"},
        ),
        (
            "record_symptom",
            {"description": "leaking", "onset": "yesterday"},
            core_tools.record_symptom,
            {"description": "leaking", "onset": "yesterday"},
        ),
        (
            "get_troubleshooting_steps",
            {"appliance": "washer", "symptom_key": "not_spinning"},
            core_tools.get_troubleshooting_steps,
            {"appliance": "washer", "symptom_key": "not_spinning"},
        ),
        (
            "update_case_file",
            {"brand": "LG", "customer_zip": "60614"},
            core_tools.update_case_file,
            {"brand": "LG", "customer_zip": "60614"},
        ),
    ],
)
async def test_ported_tool_matches_origin(tool_name, args, origin, origin_kwargs):
    """Each Pipecat tool handler returns exactly what the original app.tools.* fn returns."""
    ported_session = VoiceSession.for_call("T")
    _, handlers = build_tools(ported_session)
    ported_out = await _drive(handlers[tool_name], args)

    origin_session = VoiceSession.for_call("T")
    with origin_session.bind():
        origin_out = await origin(**origin_kwargs)

    assert ported_out == origin_out


def test_build_tools_registers_core_set_and_gates_rag(monkeypatch):
    monkeypatch.delenv("LIBRARY_RAG_ENABLED", raising=False)
    schema, handlers = build_tools(VoiceSession.for_call("T"))
    names = set(handlers)
    assert {
        "identify_appliance",
        "record_symptom",
        "get_troubleshooting_steps",
        "update_case_file",
        "find_technicians",
        "book_appointment",
        "send_image_upload_link",
        "check_image_analysis",
    } <= names
    assert "search_appliance_library" not in names  # flag off by default

    monkeypatch.setenv("LIBRARY_RAG_ENABLED", "1")
    _, handlers_on = build_tools(VoiceSession.for_call("T"))
    assert "search_appliance_library" in handlers_on


async def test_safety_gate_swallows_and_speaks():
    session = VoiceSession.for_call("T")
    gate = SafetyGateProcessor(session, LLMContext(messages=[{"role": "system", "content": "s"}]))
    down, _ = await run_test(
        gate,
        frames_to_send=[_transcription("there is sparking from the oven")],
        expected_down_frames=[TTSSpeakFrame],
    )
    assert any(isinstance(f, TTSSpeakFrame) and f.text == SAFETY_RESPONSE for f in down)
    assert not any(isinstance(f, TranscriptionFrame) for f in down)  # LLM never sees it
    assert session.case_file.safety_flag is True


async def test_safety_gate_passes_normal_utterance():
    session = VoiceSession.for_call("T")
    gate = SafetyGateProcessor(session, LLMContext(messages=[{"role": "system", "content": "s"}]))
    down, _ = await run_test(
        gate,
        frames_to_send=[_transcription("my dryer is loud")],
        expected_down_frames=[TranscriptionFrame],
    )
    assert any(isinstance(f, TranscriptionFrame) for f in down)
    assert session.case_file.safety_flag is False


def test_system_prompt_refresh_injects_live_case_file():
    session = VoiceSession.for_call("T")
    context = LLMContext(messages=[{"role": "system", "content": "placeholder"}])
    refresher = SystemPromptRefreshProcessor(session, context)

    session.case_file.appliance_type = "dishwasher"
    session.case_file.brand = "Bosch"
    refresher.refresh()

    system = context.messages[0]["content"]
    assert context.messages[0]["role"] == "system"
    assert "dishwasher" in system and "Bosch" in system  # never-re-ask: facts in the prompt


async def test_sanitizer_processor_strips_markup():
    down, _ = await run_test(
        SpokenTextSanitizer(),
        frames_to_send=[TextFrame(text="**Turn** it off. See https://ex.com now.")],
        expected_down_frames=[TextFrame],
    )
    cleaned = next(f.text for f in down if isinstance(f, TextFrame))
    assert "**" not in cleaned and "http" not in cleaned and "Turn" in cleaned


async def test_sanitizer_scrubs_llm_text_frame_subclass():
    """The LLM streams `LLMTextFrame` (a `TextFrame` subclass) token-by-token — the
    isinstance check must catch the subclass, not just the base frame."""
    from pipecat.frames.frames import LLMTextFrame

    down, _ = await run_test(
        SpokenTextSanitizer(),
        frames_to_send=[LLMTextFrame(text="**bold** word")],
        expected_down_frames=[LLMTextFrame],
    )
    cleaned = next(f.text for f in down if isinstance(f, LLMTextFrame))
    assert "**" not in cleaned and "bold" in cleaned


async def test_sanitizer_scrubs_tts_speak_frame():
    """Constant lines (greeting, safety response) reach TTS as `TTSSpeakFrame`, not via the
    LLM — the sanitizer scrubs those too, so a URL in a constant never gets read aloud."""
    down, _ = await run_test(
        SpokenTextSanitizer(),
        frames_to_send=[TTSSpeakFrame(text="Visit https://sears.com to **confirm**.")],
        expected_down_frames=[TTSSpeakFrame],
    )
    cleaned = next(f.text for f in down if isinstance(f, TTSSpeakFrame))
    assert "http" not in cleaned and "**" not in cleaned and "confirm" in cleaned


async def test_safety_gate_records_both_turns_in_context():
    """A safety interrupt appends BOTH the caller utterance and the fixed response to the
    LLM context, so history stays coherent and next turn's prompt suffix can suppress DIY
    even though the LLM never ran on this turn."""
    session = VoiceSession.for_call("T")
    context = LLMContext(messages=[{"role": "system", "content": "s"}])
    gate = SafetyGateProcessor(session, context)

    await run_test(
        gate,
        frames_to_send=[_transcription("there is sparking from the oven")],
        expected_down_frames=[TTSSpeakFrame],
    )

    roles_contents = [(m["role"], m.get("content")) for m in context.get_messages()]
    assert ("user", "there is sparking from the oven") in roles_contents
    assert ("assistant", SAFETY_RESPONSE) in roles_contents


def test_sanitize_for_speech_unit():
    out = sanitize_for_speech("- Do `this`, then [read](https://x.io) or visit www.sears.com")
    assert "`" not in out and "http" not in out and "www." not in out
    assert "read" in out and not out.startswith("-")


def test_session_id_stable_per_call_sid():
    assert VoiceSession.for_call("CA123").session_id == VoiceSession.for_call("CA123").session_id
    assert VoiceSession.for_call("CA123").session_id != VoiceSession.for_call("CA999").session_id
