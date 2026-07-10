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

from app.phone.latency import percentile  # noqa: E402

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
    # Timestamps sort lexicographically; measurement envelopes (schema v3,
    # `{ts}-measurement.json`) are aggregates, not comparable single runs — skip them.
    paths = sorted(
        p for p in reports_dir.glob("*.json") if not p.name.endswith("-measurement.json")
    )
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
            # Show the budget the summary's own pass flag was gated on (post-h1:
            # the meaningful budget); budgets_ms[budget_key] only for legacy
            # reports that predate budget_p50_ms in the e2e summary.
            "budget": a_sum.get("budget_p50_ms", after.get("budgets_ms", {}).get(budget_key)),
            "delta_pct": _delta_pct(b_p50, a_p50),
            "before_pass": b_sum.get("pass"),
            "after_pass": a_sum.get("pass"),
        }

    return stages


# Paired mode (loop v2 §2, q0-1): per-channel e2e metric + the per-record segment
# fields worth pairing when both sides carry them.
PAIRED_CHANNEL_METRICS = {
    "web": "submit_to_first_audio_ms",
    "phone": "eos_to_first_audio_ms",
}
PAIRED_SEGMENT_FIELDS = {
    "web": ("submit_to_first_token_ms", "first_token_to_first_sentence_ms"),
    "phone": (
        "eos_to_stt_ms",
        "stt_to_agent_first_token_ms",
        "agent_first_token_to_first_audio_ms",
    ),
}


def _paired_field_stats(
    before_by_key: dict[tuple, dict],
    after_by_key: dict[tuple, dict],
    field: str,
) -> dict[str, Any] | None:
    """Median of per-pair percentage deltas + sign counts for one record field.

    Pairs are records sharing (scenario_id, turn_index) with a usable (non-None,
    non-zero-before) value on both sides. Returns None when no pair qualifies.
    """
    deltas: list[float] = []
    for key, b_rec in before_by_key.items():
        a_rec = after_by_key.get(key)
        if a_rec is None:
            continue
        b_val, a_val = b_rec.get(field), a_rec.get(field)
        if b_val is None or a_val is None or not b_val:
            continue
        deltas.append((a_val - b_val) / b_val * 100)
    if not deltas:
        return None
    return {
        "n_pairs": len(deltas),
        "median_delta_pct": round(percentile(deltas, 0.50), 1),
        "improving": sum(1 for d in deltas if d < 0),
        "regressing": sum(1 for d in deltas if d > 0),
    }


def compare_paired(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Record-matched comparison (loop v2 §2): per channel, the median of per-pair
    e2e deltas plus sign counts — robust to the ±40% run-to-run scenario noise that
    made whole-run p50 deltas meaningless — and the same stats per segment field."""
    result: dict[str, Any] = {}
    for channel, metric in PAIRED_CHANNEL_METRICS.items():
        b_records = before.get("end_to_end", {}).get(channel, {}).get("records", [])
        a_records = after.get("end_to_end", {}).get(channel, {}).get("records", [])
        b_by_key = {(r.get("scenario_id"), r.get("turn_index")): r for r in b_records}
        a_by_key = {(r.get("scenario_id"), r.get("turn_index")): r for r in a_records}

        stats = _paired_field_stats(b_by_key, a_by_key, metric)
        channel_result: dict[str, Any] = {
            "metric": metric,
            "unmatched_before": len(b_by_key.keys() - a_by_key.keys()),
            "unmatched_after": len(a_by_key.keys() - b_by_key.keys()),
            **(stats or {"n_pairs": 0}),
        }
        segments = {}
        for field in PAIRED_SEGMENT_FIELDS[channel]:
            seg_stats = _paired_field_stats(b_by_key, a_by_key, field)
            if seg_stats is not None:
                segments[field] = seg_stats
        channel_result["segments"] = segments
        result[channel] = channel_result
    return result


def render_paired_table(paired: dict[str, Any], before: dict, after: dict) -> str:
    lines = [
        f"== paired compare: {before['timestamp']} -> {after['timestamp']} ==",
        f"{'channel/field':<42}{'pairs':>6}{'med delta%':>11}{'better':>7}{'worse':>6}",
    ]
    for channel, ch in paired.items():
        if ch["n_pairs"] == 0:
            lines.append(f"{channel:<42}{'0':>6}  (no matched pairs)")
            continue
        lines.append(
            f"{channel + '/' + ch['metric']:<42}{ch['n_pairs']:>6}"
            f"{ch['median_delta_pct']:>+11.1f}{ch['improving']:>7}{ch['regressing']:>6}"
        )
        for field, seg in ch["segments"].items():
            lines.append(
                f"  {channel + '/' + field:<40}{seg['n_pairs']:>6}"
                f"{seg['median_delta_pct']:>+11.1f}{seg['improving']:>7}{seg['regressing']:>6}"
            )
        if ch["unmatched_before"] or ch["unmatched_after"]:
            lines.append(
                f"  ({channel}: {ch['unmatched_before']} before-only, "
                f"{ch['unmatched_after']} after-only records skipped)"
            )
    return "\n".join(lines)


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
    parser.add_argument(
        "--paired",
        action="store_true",
        help="record-matched median-of-deltas + sign counts (loop v2 accept basis)",
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

    if args.paired:
        paired = compare_paired(before, after)
        if args.summary_json:
            print(json.dumps(paired, indent=2))
        else:
            print(render_paired_table(paired, before, after))
        return 0

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
