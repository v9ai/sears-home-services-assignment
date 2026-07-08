#!/usr/bin/env python3
"""`make transcript` — deterministic structural gate over the scenario matrix.

Fixture mode (COORDINATION.md §4): drives no live agent. Each scenario's scripted
caller turns are paired with a recorded fixture transcript
(`evals/fixtures/transcripts/<id>.json`) — a stand-in for "the agent said X and ended
up with case file Y" until voice-diagnostic-core merges and the lead flips this to a
live-agent run (see `specs/features/2026-07-08-testing-evals/plan.md` → Integration
deltas).

This module must not import `app.agent`.

Exit code 0 = every non-skipped matrix scenario passed AND every non-skipped,
structurally-checkable canary failed as designed. Exit code 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.assertions import check_structural_assertions  # noqa: E402
from evals.fixture_loader import FixtureNotFoundError, load_fixture  # noqa: E402
from evals.gating import missing_requirements  # noqa: E402
from evals.scenarios.schema import Scenario, load_scenarios  # noqa: E402


def _run_matrix(scenarios: list[Scenario]) -> bool:
    print(f"== transcript matrix ({len(scenarios)} scenarios) ==")
    failed = False
    for scenario in scenarios:
        missing = missing_requirements(scenario.requires)
        if missing:
            print(f"SKIP  {scenario.id}  (requires unmet: {', '.join(missing)})")
            continue
        try:
            fixture = load_fixture(scenario.id)
        except FixtureNotFoundError as exc:
            print(f"ERROR {scenario.id}  {exc}")
            failed = True
            continue
        result = check_structural_assertions(scenario, fixture)
        if result.ok:
            print(f"PASS  {scenario.id}")
        else:
            print(f"FAIL  {scenario.id}")
            for failure in result.failures:
                print(f"        - {failure}")
            failed = True
    return failed


def _run_canaries(canaries: list[Scenario]) -> bool:
    print(f"\n== canary suite ({len(canaries)} scenarios, expected to fail) ==")
    failed = False
    for scenario in canaries:
        missing = missing_requirements(scenario.requires)
        if missing:
            print(f"SKIP  {scenario.id}  (requires unmet: {', '.join(missing)})")
            continue
        if scenario.canary_layer == "eval":
            print(f"SKIP  {scenario.id}  (eval-layer canary — checked by `make eval`)")
            continue
        try:
            fixture = load_fixture(scenario.id)
        except FixtureNotFoundError as exc:
            print(f"ERROR {scenario.id}  {exc}")
            failed = True
            continue
        result = check_structural_assertions(scenario, fixture)
        if result.ok:
            print(f"FAIL  {scenario.id}  (canary did NOT fail structurally — harness bug)")
            failed = True
        else:
            print(f"PASS  {scenario.id}  (failed as expected: {'; '.join(result.failures)})")
    return failed


def run(scenarios_root: Path | None = None) -> int:
    scenarios = load_scenarios(scenarios_root)
    matrix = [s for s in scenarios if not s.canary]
    canaries = [s for s in scenarios if s.canary]

    matrix_failed = _run_matrix(matrix)
    canaries_failed = _run_canaries(canaries)

    print()
    if matrix_failed or canaries_failed:
        print("transcript gate: FAIL")
        return 1
    print("transcript gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
