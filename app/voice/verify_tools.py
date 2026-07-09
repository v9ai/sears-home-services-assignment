"""Offline verification for the Pipecat voice port (no live provider keys needed).

Run:  python -m app.voice.verify_tools

Checks the three things the task's Verification section asks for, without placing a real
call (which needs Deepgram/OpenAI keys + a Twilio number):

1. **Tool parity** — every ported Pipecat tool handler returns exactly what the original
   `app.tools.*` function returns for the same inputs (the deterministic core tools; the
   DB/email/RAG tools need live backends and are exercised on a real call).
2. **Guardrails fire** — the `SafetyGateProcessor` speaks `SAFETY_RESPONSE`, sets
   `safety_flag`, and swallows the transcription (so the LLM never runs) on a hazard;
   a normal utterance passes straight through.
3. **Spoken hygiene** — `SpokenTextSanitizer` strips markdown/URLs before TTS.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from app.tools import core_tools
from app.voice.session import VoiceSession
from app.voice.text import sanitize_for_speech
from app.voice.tools import build_tools

_failures: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


async def _call_handler(handler, arguments: dict) -> str:
    """Drive a ported Pipecat handler the way the LLM would, capturing result_callback."""
    captured: list[str] = []

    async def result_callback(result, **_kwargs):
        captured.append(result)

    params = SimpleNamespace(arguments=arguments, result_callback=result_callback)
    await handler(params)
    return captured[0] if captured else ""


async def verify_tool_parity() -> None:
    print("1. Tool parity (ported handler == original app.tools.* output)")

    # Each case: (tool name, LLM arguments, origin callable, origin kwargs)
    cases = [
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
        ),  # invalid -> same error string
        (
            "record_symptom",
            {"description": "won't spin", "onset": "today"},
            core_tools.record_symptom,
            {"description": "won't spin", "onset": "today"},
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
    ]

    for tool_name, args, origin_fn, origin_kwargs in cases:
        # Ported path: fresh session, driven through the Pipecat handler.
        ported_session = VoiceSession.for_call("VERIFY")
        _, handlers = build_tools(ported_session)
        ported_out = await _call_handler(handlers[tool_name], args)

        # Origin path: fresh session, ContextVars bound exactly like app.agent.core does.
        origin_session = VoiceSession.for_call("VERIFY")
        with origin_session.bind():
            origin_out = await origin_fn(**origin_kwargs)

        _check(
            f"{tool_name}({args})",
            ported_out == origin_out,
            f"ported={ported_out!r} origin={origin_out!r}",
        )

    # Safety escalation still flips safety_flag when routed through the ported handler.
    safety_session = VoiceSession.for_call("VERIFY")
    _, handlers = build_tools(safety_session)
    out = await _call_handler(
        handlers["get_troubleshooting_steps"],
        {"appliance": "washer", "symptom_key": "safety_water_near_electrics"},
    )
    _check(
        "safety symptom_key sets safety_flag + escalation text",
        safety_session.case_file.safety_flag and "SAFETY ESCALATION" in out,
        f"flag={safety_session.case_file.safety_flag} out={out[:40]!r}",
    )


async def verify_guardrails() -> None:
    print("2. Guardrails (SafetyGateProcessor, pre-LLM)")
    from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.tests.utils import run_test

    from app.agent.safety import SAFETY_RESPONSE
    from app.voice.processors import SafetyGateProcessor

    def frame(text: str) -> TranscriptionFrame:
        return TranscriptionFrame(text=text, user_id="caller", timestamp="2026-07-09T00:00:00Z")

    # Hazard: transcription swallowed, SAFETY_RESPONSE spoken, flag set.
    session = VoiceSession.for_call("VERIFY")
    context = LLMContext(messages=[{"role": "system", "content": "sys"}])
    gate = SafetyGateProcessor(session, context)
    received_down, _ = await run_test(
        gate,
        frames_to_send=[frame("I smell gas near the dryer")],
        expected_down_frames=[TTSSpeakFrame],
    )
    spoke_safety = any(
        isinstance(f, TTSSpeakFrame) and f.text == SAFETY_RESPONSE for f in received_down
    )
    swallowed = not any(isinstance(f, TranscriptionFrame) for f in received_down)
    _check("hazard -> speaks SAFETY_RESPONSE", spoke_safety)
    _check("hazard -> transcription swallowed (LLM never sees it)", swallowed)
    _check("hazard -> case_file.safety_flag set", session.case_file.safety_flag)

    # Normal utterance passes straight through untouched.
    session2 = VoiceSession.for_call("VERIFY")
    gate2 = SafetyGateProcessor(session2, LLMContext(messages=[{"role": "system", "content": "s"}]))
    received_down2, _ = await run_test(
        gate2,
        frames_to_send=[frame("my washer won't spin")],
        expected_down_frames=[TranscriptionFrame],
    )
    passed_through = any(
        isinstance(f, TranscriptionFrame) and f.text == "my washer won't spin"
        for f in received_down2
    )
    _check(
        "normal utterance -> passes through", passed_through and not session2.case_file.safety_flag
    )


def verify_sanitizer() -> None:
    print("3. Spoken hygiene (sanitize_for_speech)")
    raw = (
        "**Step 1:** unplug it. See [the manual](https://ex.com/x) "
        "or https://sears.com/help.\n- done"
    )
    cleaned = sanitize_for_speech(raw)
    _check("strips markdown emphasis", "**" not in cleaned and "Step 1:" in cleaned)
    _check("collapses [label](url) to label", "the manual" in cleaned and "](" not in cleaned)
    _check("removes bare URLs", "http" not in cleaned and "sears.com" not in cleaned)
    _check("removes list marker", not cleaned.strip().endswith("- done") and "done" in cleaned)


async def _main() -> int:
    await verify_tool_parity()
    await verify_guardrails()
    verify_sanitizer()
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
