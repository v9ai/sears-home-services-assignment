# Booking Quality Loop Ledger
state: running
iteration: 1
bench_runs_total: 1
consecutive_all_pass: 0
consecutive_no_accept: 0
branch: main

Durable state for the `/booking-quality-iterate` loop
(`.claude/skills/booking-quality-iterate/`). Counters above are the §1/§8
preconditions' source of truth; `data/` is gitignored, so report summaries live in
the per-iteration entries below.

Bootstrap (2026-07-10, `2026-07-10-booking-quality-loop/`): harness
(`evals/adaptive_driver.py`, `scripts/booking_quality_bench.py`, `make
booking-bench`), hermetic guards (`tests/test_booking_quality_policy.py`, 20
tests), and this ledger authored by the spec; a keyed harness smoke run is recorded
in the spec's validation.md. Iteration 1 (`baseline`) owns the loop's official
baseline report.

<!-- Per-iteration entries appended below by the loop. -->

## Iteration 1 — baseline — ACCEPTED

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-10T05:02:23Z",
  "fix_id": "baseline",
  "description": "Official baseline archived; bootstrap files verified already committed (f5dc7af). No code diff.",
  "baseline_report": "2026-07-10T05-00-54Z.json",
  "after_report": "2026-07-10T05-00-54Z.json",
  "target_defect": "none (neutral)",
  "scenario_flips": {"fail_to_pass": [], "pass_to_fail": []},
  "aggregate_before": {"scenarios_pass": 1, "scenarios_total": 6, "tool_exception_count": 0, "unknown_id_errors": 0, "bookings": 1, "reask_violations": 5, "total_nudges": 0},
  "aggregate_after": {"scenarios_pass": 1, "scenarios_total": 6, "tool_exception_count": 0, "unknown_id_errors": 0, "bookings": 1, "reask_violations": 5, "total_nudges": 0},
  "gates": {"lint": "clean", "test": "592 passed", "eval": "not-run (no agent diff — not mandatory)", "bench_overall": false},
  "bench_runs_this_iteration": 1,
  "db_clean_after": true,
  "decision": "accepted",
  "commit": "",
  "revert_commit": null,
  "notes": "DIAGNOSIS (transcripts read): (1) safety_interrupt FAIL is a HARNESS blind spot — the web safety gate runs in app/ws/routes.py:177 BEFORE run_turn; the driver bypasses it. (2) no_coverage FAIL is a HARNESS policy gap — terminal markers miss 'none are available'; zip branch fires on mere mention (agent acked zip while asking about the issue → policy spammed zip → groundhog loop, inflating reask_violations to 5). (3) happy_upfront transcript shows the REAL agent defect: explicit yes → agent re-runs find_technicians instead of book_appointment (confirm→re-find loop, queue #3). NEXT: bench-fidelity harness repair (reordered ahead of queue #2 per §3.5 — agent fixes judged against a noisy harness are meaningless): replicate the pre-LLM safety gate in drive_adaptive, widen no-coverage terminal markers, make fact branches fire only on actual asks; policy unit tests for each. Then queue #3 pending-booking-contract."
}
```
