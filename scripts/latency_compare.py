#!/usr/bin/env python3
"""Compare two `make latency` reports (`data/latency/*.json`, schema v2).

The latency loop's accept/revert decision helper (`.claude/skills/latency-iterate`):
prints a stage-by-stage before/after/delta table with PASS/FAIL transitions flagged,
and with ``--summary-json`` emits the exact ``stages`` object the loop ledger records
(`specs/features/2026-07-08-latency-engineering/loop-ledger.md`).

Usage:
    python scripts/latency_compare.py <before.json> <after.json> [--summary-json]
    python scripts/latency_compare.py --latest 2 [--summary-json]

Read-only and keyless — safe to run any time; exits 2 when reports are missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORTS_DIR = REPO_ROOT / "data" / "latency"

# e2e stages: ledger key -> (end_to_end channel, report p50 field, budgets_ms key)
E2E_STAGES = {
    "web_e2e_p50_ms": ("web", "p50_submit_to_first_audio_ms", "web_e2e_p50_ms"),
    "phone_e2e_p50_ms": ("phone", "p50_eos_to_first_audio_ms", "phone_e2e_p50_ms"),
}


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    version = report.get("schema_version")
    if version != 2:
        raise ValueError(f"{path.name}: expected schema_version 2, got {version!r}")
    return report


def latest_reports(n: int, reports_dir: Path = REPORTS_DIR) -> list[Path]:
    """The newest ``n`` report files, oldest first (so [0] is the 'before')."""
    if not reports_dir.is_dir():
        raise FileNotFoundError(f"no reports directory at {reports_dir} — run `make latency` first")
    paths = sorted(reports_dir.glob("*.json"))  # timestamps sort lexicographically
    if len(paths) < n:
        raise FileNotFoundError(f"need {n} reports in {reports_dir}, found {len(paths)}")
    return paths[-n:]


def _delta_pct(before: float, after: float) -> float | None:
    if not before:
        return None
    return round((after - before) / before * 100, 1)


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The ledger ``stages`` object: micro stages + e2e p50s, before/after/budget/delta."""
    stages: dict[str, dict[str, Any]] = {}

    for name, b_stage in before.get("micro_benchmarks", {}).items():
        a_stage = after.get("micro_benchmarks", {}).get(name)
        if a_stage is None:
            continue
        stages[name] = {
            "before_p50": b_stage["p50"],
            "after_p50": a_stage["p50"],
            "budget": a_stage["budget_ms"],
            "delta_pct": _delta_pct(b_stage["p50"], a_stage["p50"]),
            "before_pass": b_stage["pass"],
            "after_pass": a_stage["pass"],
        }

    for key, (channel, p50_field, budget_key) in E2E_STAGES.items():
        b_sum = before.get("end_to_end", {}).get(channel, {})
        a_sum = after.get("end_to_end", {}).get(channel, {})
        b_p50, a_p50 = b_sum.get(p50_field), a_sum.get(p50_field)
        if b_p50 is None or a_p50 is None:
            continue
        stages[key] = {
            "before_p50": b_p50,
            "after_p50": a_p50,
            "budget": after.get("budgets_ms", {}).get(budget_key),
            "delta_pct": _delta_pct(b_p50, a_p50),
            "before_pass": b_sum.get("pass"),
            "after_pass": a_sum.get("pass"),
        }

    return stages


def render_table(stages: dict[str, dict[str, Any]], before: dict, after: dict) -> str:
    lines = [
        f"== latency compare: {before['timestamp']} -> {after['timestamp']} ==",
        f"{'stage':<26}{'before':>10}{'after':>10}{'delta%':>9}{'budget':>9}  transition",
    ]
    for name, s in stages.items():
        delta = f"{s['delta_pct']:+.1f}" if s["delta_pct"] is not None else "n/a"
        budget = f"{s['budget']:.0f}" if s["budget"] is not None else "?"
        if s["before_pass"] and not s["after_pass"]:
            transition = "PASS->FAIL  <-- REGRESSION"
        elif not s["before_pass"] and s["after_pass"]:
            transition = "FAIL->PASS"
        else:
            transition = "PASS" if s["after_pass"] else "FAIL (unchanged)"
        lines.append(
            f"{name:<26}{s['before_p50']:>10.0f}{s['after_p50']:>10.0f}{delta:>9}{budget:>9}"
            f"  {transition}"
        )
    lines.append(f"overall_pass: {before.get('overall_pass')} -> {after.get('overall_pass')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path, help="before.json after.json")
    parser.add_argument(
        "--latest", type=int, metavar="N", help="compare the newest N=2 reports in data/latency/"
    )
    parser.add_argument(
        "--summary-json",
        action="store_true",
        help="emit the ledger `stages` object as JSON instead of the table",
    )
    args = parser.parse_args(argv)

    try:
        if args.latest is not None:
            if args.latest != 2:
                parser.error("--latest only supports 2")
            before_path, after_path = latest_reports(2)
        elif len(args.reports) == 2:
            before_path, after_path = args.reports
        else:
            parser.error("pass exactly two report paths, or --latest 2")
        before, after = load_report(before_path), load_report(after_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    stages = compare(before, after)
    if args.summary_json:
        # The ledger records before/after/budget/delta only — strip the pass flags.
        summary = {
            name: {k: s[k] for k in ("before_p50", "after_p50", "budget", "delta_pct")}
            for name, s in stages.items()
        }
        print(json.dumps(summary, indent=2))
    else:
        print(render_table(stages, before, after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
