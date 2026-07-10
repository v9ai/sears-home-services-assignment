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

import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from evals.live_driver import detect_reasks

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
    tools_invoked: list[str] = []

    message: str | None = opening_line(scenario)
    turns_used = 0
    while message is not None and turns_used < scenario.max_turns:
        turns.append({"role": "user", "text": message})
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
    reask_shim = SimpleNamespace(assert_=SimpleNamespace(no_reask=list(scenario.no_reask)))
    reasked = detect_reasks(agent_texts, case_file_dict, reask_shim)

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
