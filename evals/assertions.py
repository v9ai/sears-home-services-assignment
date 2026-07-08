"""Deterministic structural assertions over a recorded fixture transcript.

These back `make transcript` — a hard pass/fail gate, no LLM judgment involved
(requirements.md → Included: "case-file contents, safety routing, booking row").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.scenarios.schema import Scenario

_MISSING = object()


def _get_path(data: Any, dotted: str) -> Any:
    node = data
    for part in dotted.split("."):
        if isinstance(node, list):
            if not part.lstrip("-").isdigit():
                return _MISSING
            index = int(part)
            if index >= len(node) or index < -len(node):
                return _MISSING
            node = node[index]
        elif isinstance(node, dict):
            if part not in node:
                return _MISSING
            node = node[part]
        else:
            return _MISSING
    return node


@dataclass
class AssertionResult:
    ok: bool
    failures: list[str] = field(default_factory=list)


def check_structural_assertions(scenario: Scenario, fixture: dict[str, Any]) -> AssertionResult:
    """Check a fixture transcript's recorded case file + flags against a scenario's
    `assert:` block. Returns every failure found (not just the first) so a runner or
    test can report the full defect list."""
    failures: list[str] = []
    case_file = fixture.get("case_file", {})
    flags = fixture.get("flags", {})

    for path, expected in scenario.assert_.facts.items():
        actual = _get_path(case_file, path)
        if actual is _MISSING:
            failures.append(f"fact {path!r} missing from case file")
        elif actual != expected:
            failures.append(f"fact {path!r} = {actual!r}, expected {expected!r}")

    reasked = set(flags.get("reasked_fields", []))
    for path in scenario.assert_.no_reask:
        if path in reasked:
            failures.append(f"field {path!r} was re-asked (never-re-ask violation)")

    actual_safety = bool(flags.get("safety_interrupt", False))
    if actual_safety != scenario.assert_.safety_interrupt:
        failures.append(
            f"safety_interrupt = {actual_safety}, expected {scenario.assert_.safety_interrupt}"
        )

    actual_booking = bool(flags.get("booking_row", False))
    if actual_booking != scenario.assert_.booking_row:
        failures.append(f"booking_row = {actual_booking}, expected {scenario.assert_.booking_row}")

    return AssertionResult(ok=not failures, failures=failures)
