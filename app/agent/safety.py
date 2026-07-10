"""Deterministic safety-interrupt detector (mission non-negotiable 1).

"Any mention of gas smell, sparking, burning smell, smoke, or water near electrics
halts troubleshooting immediately... No flow may route around this." That's enforced
structurally the same way the case file enforces never-re-ask: this check runs on the
raw user utterance *before* the agent/tool-calling loop ever sees it, so it can't be
argued around by prompt drift or a model choosing not to call a tool.
"""

from __future__ import annotations

import re

SafetyCategory = str

# Shared vocabulary fragments. _ELECTRICS/_PROXIMITY are interpolated into the
# water pattern; keeping them named stops the connective and device lists from
# drifting apart between the forward and reverse directions.
_ELECTRICS = r"(?:outlet|electric|electrical|panel|breaker|plug|cord|wiring)"
_PROXIMITY = r"(?:near|by|around|touching|close\s+to|in|into|inside|on|onto|under|behind)"

_PATTERNS: dict[SafetyCategory, re.Pattern[str]] = {
    "gas_smell": re.compile(
        r"\b(?:gas|propane)\s*(?:smell|leak|odor|fumes)|"
        r"\bsmell(?:s|ing)?\s+(?:like\s+|of\s+)?(?:gas|propane|fumes)\b|"
        r"rotten\s*egg",
        re.IGNORECASE,
    ),
    "sparking": re.compile(r"\bspark(?:s|ing|ed)?\b|\barc(?:s|ing|ed)?\b", re.IGNORECASE),
    "burning_smell": re.compile(
        r"\bburn(?:ing|t)?\s*smell\b|\bsmells?\s+(?:like\s+)?burn(?:ing|t)?\b|"
        r"\bsmell(?:s|ing)?\s+(?:of\s+)?(?:something\s+)?burn(?:ing|t)?\b",
        re.IGNORECASE,
    ),
    "smoke": re.compile(r"\bsmok(?:e|ing|y|ey)\b", re.IGNORECASE),
    "water_near_electrics": re.compile(
        rf"\bwater\b[^.!?]{{0,40}}\b{_PROXIMITY}\b[^.!?]{{0,20}}{_ELECTRICS}|"
        rf"{_ELECTRICS}[^.!?]{{0,40}}\b{_PROXIMITY}\b[^.!?]{{0,20}}\bwater\b|"
        rf"\b(?:leak(?:s|ing|ed)?|drip(?:s|ping|ped)?)\b[^.!?]{{0,30}}\b{_PROXIMITY}\b"
        rf"[^.!?]{{0,20}}{_ELECTRICS}|"
        rf"\bwet\b[^.!?]{{0,20}}{_ELECTRICS}|{_ELECTRICS}s?\b[^.!?]{{0,20}}\bwet\b",
        re.IGNORECASE,
    ),
}

SAFETY_RESPONSE = (
    "That's not something to troubleshoot yourself. For your safety, please stop using "
    "the appliance right now and turn off its power at the source — and the gas supply "
    "too, if this involves gas. If you smell gas, see smoke, or notice sparking, leave "
    "the area and call your gas utility or 911 before doing anything else. I can have a "
    "certified Sears technician come take a look instead — would you like me to get that "
    "scheduled for you?"
)


def detect_safety_trigger(text: str) -> SafetyCategory | None:
    """Return the matched safety category, or ``None`` if nothing triggers.

    Checks every category and returns the first match in a fixed, deterministic order
    so behavior is stable and testable regardless of dict ordering.
    """
    for category in ("gas_smell", "smoke", "sparking", "burning_smell", "water_near_electrics"):
        if _PATTERNS[category].search(text):
            return category
    return None
