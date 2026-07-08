#!/usr/bin/env python3
"""`make transcript` — structural gate over the scenario matrix.

Two modes:

- **Fixture mode (default; COORDINATION.md §4).** Drives no live agent. Each scenario's
  scripted caller turns are paired with a recorded fixture transcript
  (`evals/fixtures/transcripts/<id>.json`). Deterministic and offline — the CI gate.
  This path never imports `app.agent` (the lazy live import below keeps that true).
- **Live mode (`--live`; the post-integration flip, COORDINATION.md §5 step 3).** Drives
  each matrix scenario's caller turns through the real agent via `evals.live_driver`,
  producing the same fixture-shaped result the structural assertions consume. Needs a
  configured LLM key (OPENAI/DEEPSEEK per `LLM_PROVIDER`) and, for scheduling/visual
  scenarios, a migrated + seeded database. Canaries are deliberate-failure *fixtures*, so
  they stay fixture-based in both modes.

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


def _drive_live(scenario: Scenario, llm: object) -> dict:
    """Run a scenario through the real agent, returning a fixture-shaped transcript.

    Imported lazily so the default fixture path never pulls in `app.agent`.
    """
    import asyncio

    from evals.live_driver import drive_scenario

    return asyncio.run(drive_scenario(scenario, llm=llm))


def _run_matrix(scenarios: list[Scenario], *, live: bool = False, llm: object = None) -> bool:
    mode = "live" if live else "fixture"
    print(f"== transcript matrix ({len(scenarios)} scenarios, {mode} mode) ==")
    failed = False
    for scenario in scenarios:
        missing = missing_requirements(scenario.requires)
        if missing:
            print(f"SKIP  {scenario.id}  (requires unmet: {', '.join(missing)})")
            continue
        try:
            fixture = _drive_live(scenario, llm) if live else load_fixture(scenario.id)
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


def run(scenarios_root: Path | None = None, *, live: bool = False) -> int:
    scenarios = load_scenarios(scenarios_root)
    matrix = [s for s in scenarios if not s.canary]
    canaries = [s for s in scenarios if s.canary]

    llm = None
    if live:
        from app.agent.core import get_llm

        llm = get_llm()

    matrix_failed = _run_matrix(matrix, live=live, llm=llm)
    # Canaries are deliberate-failure fixtures — always fixture-based, never live.
    canaries_failed = _run_canaries(canaries)

    print()
    if matrix_failed or canaries_failed:
        print("transcript gate: FAIL")
        return 1
    print("transcript gate: PASS")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="transcript structural gate")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--live",
        action="store_true",
        help="drive the real agent (needs an LLM key + migrated/seeded DB)",
    )
    group.add_argument(
        "--fixtures",
        action="store_true",
        help="use recorded fixtures (default; deterministic, offline)",
    )
    args = parser.parse_args()
    raise SystemExit(run(live=args.live))
