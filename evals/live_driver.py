"""Live-agent driver for the scenario matrix (post-integration, COORDINATION.md §5 step 3).

The fixture harness (``fixture_loader.py`` — the default ``make transcript`` path) never
imports ``app.agent`` (COORDINATION.md §4). This module is the integration-time flip the
testing-evals plan reserved: it drives each scenario's scripted caller turns through the
REAL agent (``app.agent.core.run_turn``) and emits the same fixture-shaped dict
(``{"turns", "case_file", "flags"}``) that ``evals.assertions.check_structural_assertions``
and the DeepEval metrics already consume — so nothing downstream changes shape.

The ``app.agent`` import is deliberately lazy (inside ``drive_scenario``) so importing
this module, or the default fixture path, stays free of the agent/LLM dependency until a
live run is actually requested.

Flag semantics (mirrors the hand-authored fixture ``flags`` block):
- ``safety_interrupt``  — the resulting case file's ``safety_flag`` (set by the safety
  tool path); rock-solid, read straight off the mutated case file.
- ``booking_row``       — whether a booking landed. By default this is "``book_appointment``
  was invoked this run" (the tool only writes a confirmed row on success, and re-offers
  alternatives on ``slot_taken`` without a second call for the taken slot). Pass a
  ``booking_probe`` to instead assert against a real ``appointments`` row by session id.
- ``reasked_fields``    — best-effort keyword heuristic (``detect_reasks``): a tracked
  field counts as re-asked only if its value is already captured AND a later agent turn
  interrogates for it again. Injectable via ``reask_detector`` for stricter checks.

Canaries are deliberate-failure *fixtures* (requirements.md → Decisions #3); driving the
real agent through one would defeat its purpose, so live mode only ever drives the
non-canary matrix (see ``scripts/transcript_runner.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from evals.scenarios.schema import Scenario

BookingProbe = Callable[[uuid.UUID | None], Awaitable[bool]]
ReaskDetector = Callable[[list[str], dict[str, Any], Scenario], list[str]]

# Dotted case-file field -> interrogative keywords that signal the agent asking for it.
_REASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "customer.zip": ("zip", "postal code", "zip code"),
    "customer.email": ("email", "e-mail"),
    "brand": ("brand", "make", "manufacturer"),
    "appliance_type": ("appliance", "what kind of", "which appliance"),
}
_INTERROGATIVE_MARKERS = (
    "?",
    "what's your",
    "what is your",
    "can you give me",
    "could you give me",
    "can i get your",
    "remind me",
    "what was your",
)


def _get_path(data: Any, dotted: str) -> Any:
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def detect_reasks(
    agent_texts: list[str], case_file: dict[str, Any], scenario: Scenario
) -> list[str]:
    """Flag any ``no_reask`` field the agent interrogated for despite already having it.

    Heuristic, not a parser: a field is flagged only when (a) its value is present in the
    resulting case file and (b) some agent turn both mentions the field's keyword and
    reads as a question. Good enough to catch a blatant re-ask (the knowledge-retention
    canary) without false-positiving on the agent merely *referencing* a captured fact.
    """
    reasked: list[str] = []
    for field in scenario.assert_.no_reask:
        if _get_path(case_file, field) in (None, ""):
            continue
        keywords = _REASK_KEYWORDS.get(field)
        if not keywords:
            continue
        for text in agent_texts:
            lowered = text.lower()
            if any(kw in lowered for kw in keywords) and any(
                marker in lowered for marker in _INTERROGATIVE_MARKERS
            ):
                reasked.append(field)
                break
    return reasked


async def drive_scenario(
    scenario: Scenario,
    *,
    llm: Any = None,
    session_id: uuid.UUID | None = None,
    booking_probe: BookingProbe | None = None,
    reask_detector: ReaskDetector | None = None,
    collect_latency: bool = False,
) -> dict[str, Any]:
    """Drive one scenario's caller turns through the real agent; return a fixture dict.

    ``llm`` defaults to whatever ``build_agent`` resolves (the configured provider); pass a
    scripted fake for deterministic, offline tests. ``session_id`` is threaded to the
    session-scoped tools (visual uploads); leave ``None`` to run without a persisted
    session (core scenarios need no DB). ``collect_latency`` (default ``False``, so every
    existing caller's behavior is unchanged) synthesizes each turn's first sentence to
    stamp a latency-engineering ``TurnTrace`` per turn, returned under the ``"trace"`` key
    (``[]`` when the flag is off, so the shape never varies with it).
    """
    from llama_index.core.memory import ChatMemoryBuffer

    from app.agent.core import SentenceReady, ToolInvoked, run_turn
    from app.agent.prompts import GREETING
    from app.agent.trace import TurnTrace
    from app.agent.tts import synthesize
    from app.contracts import CaseFile

    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    turns: list[dict[str, str]] = [{"role": "agent", "text": GREETING}]
    agent_texts: list[str] = []
    tools_invoked: list[str] = []
    trace_records: list[dict[str, Any]] = []

    for turn_index, turn in enumerate(scenario.turns):
        turns.append({"role": "user", "text": turn.caller})
        trace = None
        if collect_latency:
            trace = TurnTrace(channel="web", scenario_id=scenario.id, turn_index=turn_index)
            trace.mark("t0")
        sentences: list[str] = []
        async for event in run_turn(
            case_file, memory, turn.caller, session_id=session_id, llm=llm, trace=trace
        ):
            if isinstance(event, ToolInvoked):
                tools_invoked.append(event.tool_name)
            elif isinstance(event, SentenceReady):
                sentences.append(event.text)
        agent_text = " ".join(sentences)
        turns.append({"role": "agent", "text": agent_text})
        agent_texts.append(agent_text)
        if trace is not None:
            if sentences:
                async for chunk in synthesize(sentences[0]):
                    if chunk:
                        trace.mark("first_audio")
                        break
            trace.mark("turn_done")
            trace_records.append(trace.to_record())

    case_file_dict = case_file.model_dump(mode="json")

    if booking_probe is not None:
        booking_row = await booking_probe(session_id)
    else:
        booking_row = "book_appointment" in tools_invoked

    detector = reask_detector or detect_reasks
    reasked = detector(agent_texts, case_file_dict, scenario)

    return {
        "turns": turns,
        "case_file": case_file_dict,
        "flags": {
            "safety_interrupt": bool(case_file_dict.get("safety_flag", False)),
            "booking_row": bool(booking_row),
            "reasked_fields": reasked,
        },
        "trace": trace_records,
    }
