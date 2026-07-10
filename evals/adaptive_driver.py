"""Adaptive live driver (2026-07-10-booking-quality-loop).

`drive_scenario` (live_driver.py) replays FIXED caller turns — fine for judged
metrics, structurally blind to conversation-flow defects: a live agent that loses
its slot list, loops on confirmation, or re-asks for captured facts diverges from
the script and the drive just fizzles. This module drives the REAL agent with a
deterministic **reply policy**: each caller turn is chosen from the agent's last
utterance by a keyword state machine, so live drives converge (or fail) the way a
cooperative human caller would — repeatably enough to diff run-over-run.

Everything here is deterministic given the agent's outputs; all model
nondeterminism is confined to the agent under test.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from evals.live_driver import _INTERROGATIVE_MARKERS, _REASK_KEYWORDS

MAX_TURNS_DEFAULT = 8

# Coverage-gap phrasings the live agent actually uses (bench-fidelity, loop i2):
# "no available technicians", "none are available right now", "no dishwasher
# technicians available", "not able to find", "couldn't find".
_NO_COVERAGE_RE = re.compile(
    r"\b(?:no|none|not|couldn'?t)\b[^.?!]{0,60}\b(?:technicians?|available|find)\b"
)


@dataclass(frozen=True)
class AdaptiveScenario:
    """One adaptive drive: an opening line plus the facts the policy may reveal."""

    id: str
    appliance: str
    symptom: str  # spoken symptom clause, e.g. "won't drain — standing water"
    zip: str
    name: str = "Jamie Rivera"
    email: str = "jamie@bench.example.test"
    upfront: bool = True  # False = drip-fed: facts revealed only when asked
    safety_line: str | None = None  # injected as turn 2 when set (safety scenario)
    expect_no_tech: bool = False  # success = honest no-coverage handling, no booking
    expect_conflict: bool = False  # bench arms an out-of-band claim; slot_taken must surface
    turn_budget: int = 7  # scoring bound on caller turns for booking scenarios
    max_turns: int = MAX_TURNS_DEFAULT
    no_reask: tuple[str, ...] = ("appliance_type", "customer.zip", "customer.email")


@dataclass
class PolicyState:
    """What the scripted caller has already revealed / done."""

    gave_details: bool = False
    gave_zip: bool = False
    gave_name_email: bool = False
    said_safety: bool = False
    accepted_slot: bool = False
    nudges: int = 0  # generic fallback replies used (a divergence smell, capped)


def _fact_value(field: str, scenario: AdaptiveScenario) -> str:
    return {
        "customer.zip": scenario.zip,
        "customer.email": scenario.email,
        "appliance_type": scenario.appliance,
    }.get(field, "")


def detect_reasks_ordered(
    caller_texts: list[str], agent_texts: list[str], scenario: AdaptiveScenario
) -> list[str]:
    """Order-aware re-ask detection for adaptive drives (loop i3).

    `evals.live_driver.detect_reasks` checks only "value present in the FINAL case
    file", which is right for fixture transcripts (facts given upfront) but
    structurally wrong for adaptive drives: it flags every legitimate FIRST
    elicitation on the drip-fed path, and it flags the agent merely ECHOING a value
    inside an offer ("…for your washer in zip code 60601 — which time…?").

    Here a field counts as re-asked only when an agent turn (a) mentions the field's
    keyword, (b) reads as a question, (c) does NOT contain the value (echo ≠ ask),
    and (d) comes AFTER the caller turn that stated the value. `agent_texts[i]` is
    the reply to `caller_texts[i]`.
    """
    reasked: list[str] = []
    for field in scenario.no_reask:
        value = _fact_value(field, scenario).lower()
        keywords = _REASK_KEYWORDS.get(field)
        if not value or not keywords:
            continue
        stated_at: int | None = None
        for i, caller in enumerate(caller_texts):
            if value in caller.lower():
                stated_at = i
                break
        if stated_at is None:
            continue  # never stated — any agent ask was a legitimate elicitation
        for i, agent in enumerate(agent_texts):
            if i < stated_at:
                continue  # asked before the caller stated it — legitimate
            turn = agent.lower()
            if value in turn:
                continue  # echoes the value — referencing, not asking
            mentions = any(k in turn for k in keywords)
            interrogative = "?" in turn or any(m in turn for m in _INTERROGATIVE_MARKERS)
            if mentions and interrogative:
                reasked.append(field)
                break
    return reasked


def opening_line(scenario: AdaptiveScenario) -> str:
    if scenario.upfront:
        return (
            f"My {scenario.appliance} {scenario.symptom}. I've already tried the "
            "basics; I just need a technician appointment, no troubleshooting. "
            f"My zip is {scenario.zip}, my name is {scenario.name}, "
            f"email {scenario.email}."
        )
    return f"Hi — my {scenario.appliance} {scenario.symptom}. Can someone come fix it?"


def reply_policy(agent_text: str, scenario: AdaptiveScenario, state: PolicyState) -> str | None:
    """Next caller line, or None when the conversation reached its end state.

    Priority order matters: terminal detection first, then direct questions, then
    slot handling, then generic nudges. Every branch mutates `state` so repeated
    agent questions get consistent (re-ask-detectable) answers.
    """
    t = agent_text.lower()

    # Terminal: booked. (The bench separately verifies the DB row — this only ends
    # the conversation loop.)
    if any(
        marker in t
        for marker in (
            "confirmation number",
            "you're all set",
            "is confirmed",
            "booked for",
            "is booked",
        )
    ):
        return None

    # Terminal: honest no-coverage handling for the no-tech scenario (regex covers
    # the observed live phrasings — bench-fidelity, loop i2).
    if scenario.expect_no_tech and _NO_COVERAGE_RE.search(t):
        return None

    # Safety scenario: inject the hazard once, early.
    if scenario.safety_line and not state.said_safety:
        state.said_safety = True
        return scenario.safety_line

    # Direct fact questions FIRST — "could you confirm your name/zip/email?" must be
    # answered with the facts, not a booking yes. (Drip-fed path; on the upfront path
    # these are exactly the re-asks `detect_reasks` flags — answer anyway so the
    # drive can still converge.)
    asks = "?" in t or "could you" in t or "can you" in t or "please tell" in t or "remind me" in t
    # Value guards (bench-fidelity, loop i2): an agent line that ECHOES the value
    # ("Thanks for sharing your zip code 60614 … what issue…?") is an acknowledgment,
    # not a question for it — answering zip to it caused a groundhog loop that
    # inflated reask_violations.
    if asks and ("zip" in t or "postal" in t) and scenario.zip not in t:
        state.gave_zip = True
        return f"My zip code is {scenario.zip}."
    if (
        asks
        and ("email" in t or "your name" in t or "contact" in t)
        and scenario.email.lower() not in t
        and scenario.name.lower() not in t
    ):
        state.gave_name_email = True
        return f"My name is {scenario.name} and my email is {scenario.email}."
    if (
        "which appliance" in t
        or "what appliance" in t
        or "which issue" in t
        or "what issue" in t
        or (asks and "symptom" in t)
    ):
        state.gave_details = True
        return f"It's the {scenario.appliance} — it {scenario.symptom}."

    # Confirmation question → explicit yes (never volunteer new slot choices here).
    # "correct?" / "yes or no" cover the read-back phrasings observed live (i2).
    if (
        "is that correct" in t
        or "correct?" in t
        or "yes or no" in t
        or "shall i book" in t
        or ("should i" in t and "book" in t)
        or "to confirm" in t
    ):
        state.accepted_slot = True
        return "Yes, that's correct — please book it now."

    # Agent lost its offer list ("I don't see the list…") → point it back at the tool.
    if "don't see" in t or "don't have the list" in t or "which day" in t:
        return (
            f"Please run find_technicians again for my {scenario.appliance} in "
            f"{scenario.zip} and book the first available slot — yes, I confirm."
        )

    # Slot offers → deterministic: always take the first.
    if (
        "which time" in t
        or "works best" in t
        or "which of" in t
        or ("slot" in t and "?" in t)
        or "which works" in t
    ):
        state.accepted_slot = True
        return "The first option you just listed works — please book that exact slot now."

    # Slot got taken (conflict scenario) → accept the re-offer.
    if "no longer available" in t or "just taken" in t or "was taken" in t:
        state.accepted_slot = True
        return "That's fine — the next available option works. Please book it."

    # Offers to search / schedule → accept.
    if "would you like" in t and (
        "find" in t or "schedule" in t or "technician" in t or "appointment" in t
    ):
        return "Yes please, find the available technicians now."

    # Troubleshooting drift → redirect to booking (except the safety scenario, where
    # the agent SHOULD refuse troubleshooting on its own).
    if "troubleshoot" in t or "steps" in t or "let's start by" in t:
        return (
            "No troubleshooting please — I already tried everything. "
            "Please just book the technician appointment."
        )

    # Generic nudge (divergence smell — counted).
    state.nudges += 1
    return "Please go ahead and book the soonest available slot — yes, I confirm."


async def drive_adaptive(
    scenario: AdaptiveScenario,
    *,
    llm: Any = None,
    session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Drive one adaptive scenario through the real agent; return metrics + turns.

    Lazy agent import, mirroring `drive_scenario` — importing this module stays free
    of the agent/LLM dependency. The caller owns session-row seeding, tool wiretaps,
    and DB assertions (see `scripts/booking_quality_bench.py`).
    """
    from llama_index.core.memory import ChatMemoryBuffer

    from app.agent.core import SentenceReady, ToolInvoked, run_turn
    from app.agent.prompts import GREETING
    from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
    from app.contracts import CaseFile

    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    state = PolicyState()

    turns: list[dict[str, str]] = [{"role": "agent", "text": GREETING}]
    agent_texts: list[str] = []
    caller_texts: list[str] = []
    tools_invoked: list[str] = []

    message: str | None = opening_line(scenario)
    turns_used = 0
    while message is not None and turns_used < scenario.max_turns:
        turns.append({"role": "user", "text": message})
        caller_texts.append(message)
        turns_used += 1
        # Channel-fidelity (bench-fidelity, loop i2): the web channel runs the safety
        # interrupt on the raw utterance BEFORE the agent (app/ws/routes.py) — set the
        # flag, speak the fixed response, skip the agent for this turn. Without this
        # the bench measures a path no channel actually exposes.
        if detect_safety_trigger(message) is not None:
            case_file.safety_flag = True
            agent_text = SAFETY_RESPONSE
        else:
            sentences: list[str] = []
            async for event in run_turn(case_file, memory, message, session_id=session_id, llm=llm):
                if isinstance(event, ToolInvoked):
                    tools_invoked.append(event.tool_name)
                elif isinstance(event, SentenceReady):
                    sentences.append(event.text)
            agent_text = " ".join(sentences)
        turns.append({"role": "agent", "text": agent_text})
        agent_texts.append(agent_text)
        message = reply_policy(agent_text, scenario, state)

    case_file_dict = case_file.model_dump(mode="json")
    reasked = detect_reasks_ordered(caller_texts, agent_texts, scenario)

    return {
        "scenario_id": scenario.id,
        "turns": turns,
        "turns_used": turns_used,
        "converged": message is None,  # policy reached a terminal state before max_turns
        "case_file": case_file_dict,
        "tools_invoked": tools_invoked,
        "reasked_fields": reasked,
        "nudges": state.nudges,
        "safety_flag": bool(case_file_dict.get("safety_flag", False)),
    }


# ---------------------------------------------------------------------------
# LLM-caller e2e drives (2026-07-10 live-e2e-personas).
#
# `drive_adaptive` above uses a deterministic keyword reply policy — repeatable,
# but structurally cooperative: it can never *interrupt*, *change its mind*, probe
# an injection, or phrase a fact three different ways. These drives put a real LLM
# in the caller's seat instead: a persona system prompt + a bounded chat loop where
# the agent's spoken turns are fed back to the caller model, which decides the next
# line entirely in character. The only nondeterminism the agent-under-test sees is
# thus a *human-shaped* caller, which is exactly the coverage the fixed policy can't
# reach. Cost is bounded by `CallerPersona.max_turns` and the terse-reply contract.
# ---------------------------------------------------------------------------

# Agent lines that end a booking conversation (superset of the policy's terminal
# markers) — used to stop the loop even if the LLM caller keeps chatting past a
# confirmation, so a runaway persona can't burn the whole turn budget.
_BOOKING_TERMINAL = (
    "confirmation number",
    "you're all set",
    "is confirmed",
    "booked for",
    "is booked",
    "all booked",
)

# The caller model emits this alone on a line when its goal is met (booked, told no
# coverage, or otherwise satisfied). Kept angle-bracketed so it never collides with a
# natural spoken phrase.
CALLER_END = "<END>"

_CALLER_CONTRACT = (
    "You are a person phoning the Sears Home Services line. Stay fully in character as "
    "the caller described below; you are NOT an assistant and never break character or "
    "mention being an AI. Reply with ONE short, natural spoken line — at most two "
    "sentences, no lists, no stage directions, no quotation marks. Answer the agent's "
    "questions the way your persona would. When your goal is fully met — the agent has "
    "confirmed a booking, told you no technician is available, or otherwise resolved "
    f"your call — reply with exactly {CALLER_END} on its own and nothing else. Do not "
    f"emit {CALLER_END} before your goal is met."
)


@dataclass(frozen=True)
class CallerPersona:
    """One LLM-driven caller: a persona prompt, a fixed opening line, and bounds.

    `opening_line` is deterministic (the caller model never generates turn 1) so every
    drive starts from the same premise and only the agent's handling varies. `goal`
    is folded into the caller's system prompt; `max_turns` bounds caller turns for cost.
    """

    id: str
    goal: str  # what this caller wants + how they behave, in the second person
    opening_line: str
    max_turns: int = 6


def build_caller_llm(temperature: float = 0.4) -> Any:
    """LLM that plays the caller — same provider as the agent (`app.agent.core.get_llm`),
    but a fresh instance at a mild temperature so personas feel human, not scripted.

    Reuses the agent's provider resolution (DeepSeek by default; `LLM_PROVIDER=openai`
    falls back) so a live run needs exactly the one key the agent already requires — no
    second provider to configure. Import stays lazy: importing this module never pulls
    the LLM stack until a live drive actually builds a caller.
    """
    provider = os.environ.get("LLM_PROVIDER", "deepseek").strip().lower()
    if provider == "openai":
        from llama_index.llms.openai import OpenAI

        return OpenAI(model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4o"), temperature=temperature)
    from llama_index.llms.deepseek import DeepSeek

    return DeepSeek(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        temperature=temperature,
    )


def _caller_system_prompt(persona: CallerPersona) -> str:
    return f"{_CALLER_CONTRACT}\n\nYour persona and goal:\n{persona.goal}"


async def _next_caller_line(
    caller_llm: Any, system_prompt: str, transcript: list[dict[str, str]]
) -> str:
    """Ask the caller LLM for its next line given the running transcript.

    The agent's turns are the *user* side from the caller model's point of view (it is
    hearing the agent), and the caller's own prior lines are the *assistant* side. The
    fixed greeting/opening are already in `transcript`, so this only ever runs from
    turn 2 onward.
    """
    from llama_index.core.llms import ChatMessage, MessageRole

    messages = [ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)]
    for entry in transcript:
        role = MessageRole.USER if entry["role"] == "agent" else MessageRole.ASSISTANT
        messages.append(ChatMessage(role=role, content=entry["text"]))
    response = await caller_llm.achat(messages)
    return (response.message.content or "").strip()


async def drive_llm_caller(
    persona: CallerPersona,
    *,
    agent_llm: Any = None,
    caller_llm: Any = None,
    session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Drive one LLM-caller persona through the real agent loop; return metrics + turns.

    Mirrors `drive_adaptive`'s shape (lazy agent import, same channel-fidelity safety
    short-circuit) so downstream assertion helpers consume it unchanged. `caller_llm`
    defaults to `build_caller_llm()`; inject a scripted fake for an offline unit test.
    The loop stops when the caller emits `CALLER_END`, the agent speaks a booking
    terminal, or `persona.max_turns` caller turns elapse (whichever comes first).
    """
    from llama_index.core.memory import ChatMemoryBuffer

    from app.agent.core import SentenceReady, ToolInvoked, run_turn
    from app.agent.prompts import GREETING
    from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger
    from app.contracts import CaseFile

    caller = caller_llm if caller_llm is not None else build_caller_llm()
    system_prompt = _caller_system_prompt(persona)

    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=agent_llm)

    turns: list[dict[str, str]] = [{"role": "agent", "text": GREETING}]
    agent_texts: list[str] = []
    caller_texts: list[str] = []
    tools_invoked: list[str] = []
    # Wall-clock of each agent turn (the `run_turn` span only — excludes the caller-LLM
    # think time, which is the driver's cost, not the agent's). Feeds the live per-turn
    # latency budget (evals/test_e2e_live_latency.py). Safety-short-circuit turns don't
    # touch the agent, so they're not timed.
    turn_latencies_s: list[float] = []

    message: str = persona.opening_line
    turns_used = 0
    ended_by = "max_turns"
    while turns_used < persona.max_turns:
        turns.append({"role": "user", "text": message})
        caller_texts.append(message)
        turns_used += 1

        # Channel-fidelity: the web channel runs the safety interrupt on the raw
        # utterance BEFORE the agent (app/ws/routes.py); mirror it so the drive
        # measures a path a real channel exposes (same short-circuit as drive_adaptive).
        if detect_safety_trigger(message) is not None:
            case_file.safety_flag = True
            agent_text = SAFETY_RESPONSE
        else:
            sentences: list[str] = []
            _t0 = time.monotonic()
            async for event in run_turn(
                case_file, memory, message, session_id=session_id, llm=agent_llm
            ):
                if isinstance(event, ToolInvoked):
                    tools_invoked.append(event.tool_name)
                elif isinstance(event, SentenceReady):
                    sentences.append(event.text)
            turn_latencies_s.append(time.monotonic() - _t0)
            agent_text = " ".join(sentences)

        turns.append({"role": "agent", "text": agent_text})
        agent_texts.append(agent_text)

        if any(marker in agent_text.lower() for marker in _BOOKING_TERMINAL):
            ended_by = "terminal"
            break

        reply = await _next_caller_line(caller, system_prompt, turns)
        if not reply or CALLER_END in reply:
            ended_by = "caller"
            break
        message = reply

    case_file_dict = case_file.model_dump(mode="json")
    return {
        "persona_id": persona.id,
        "turns": turns,
        "agent_texts": agent_texts,
        "caller_texts": caller_texts,
        "turns_used": turns_used,
        "converged": ended_by in ("caller", "terminal"),
        "ended_by": ended_by,
        "case_file": case_file_dict,
        "tools_invoked": tools_invoked,
        "safety_flag": bool(case_file_dict.get("safety_flag", False)),
        "turn_latencies_s": turn_latencies_s,
    }
