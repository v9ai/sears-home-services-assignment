# Booking Quality Loop Ledger
state: running
iteration: 2
bench_runs_total: 2
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

## Iteration 2 — bench-fidelity — ACCEPTED

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-10T05:25:00Z",
  "fix_id": "bench-fidelity",
  "description": "Harness repair (reordered ahead of queue #2, rationale in i1): replicate the web channel's pre-LLM safety gate in drive_adaptive (detect_safety_trigger -> safety_flag + SAFETY_RESPONSE, agent skipped, exactly app/ws/routes.py); policy value-guards (zip/email/name branches no longer fire on value-echo acknowledgments — kills the zip groundhog loop); no-coverage terminal regex covering observed live phrasings; 'correct?'/'yes or no'/'is booked' markers. 6 new policy tests.",
  "baseline_report": "2026-07-10T05-00-54Z.json",
  "after_report": "2026-07-10T05-21-26Z.json",
  "target_defect": "harness fidelity (safety-gate bypass + policy false triggers)",
  "scenario_flips": {"fail_to_pass": ["safety_interrupt"], "pass_to_fail": []},
  "aggregate_before": {"scenarios_pass": 1, "scenarios_total": 6, "tool_exception_count": 0, "unknown_id_errors": 0, "bookings": 1, "reask_violations": 5, "total_nudges": 0},
  "aggregate_after": {"scenarios_pass": 2, "scenarios_total": 6, "tool_exception_count": 0, "unknown_id_errors": 0, "bookings": 3, "reask_violations": 5, "total_nudges": 1},
  "gates": {"lint": "clean on this iteration's files (repo-wide red only on a parallel session's in-flight scripts/call_audio_report.py)", "test": "608 passed (full suite)", "eval": "not-run (pure-harness diff — not mandatory)", "bench_overall": false},
  "bench_runs_this_iteration": 1,
  "db_clean_after": true,
  "decision": "accepted",
  "commit": "",
  "revert_commit": null,
  "notes": "After-bench transcripts expose two REMAINING instrument defects: (1) reask detector false-positives — flags the agent ECHOING 'zip code 60601' inside a slot offer (reask_trap booked cleanly in 2 turns yet flagged), and structurally flags every legitimate FIRST elicitation in drip-fed drives because it only checks 'value present in FINAL case file'; needs an order-aware detector inside adaptive_driver (flag asks only AFTER the caller stated the fact). (2) no_coverage's symptom 'smells burnt' trips the now-correctly-replicated safety gate — scenario measures the wrong thing; symptom must be safety-neutral (scenario-intent repair, recorded openly: this changes a pinned scenario's wording, NOT its success rule). Real agent signal persisting: happy_upfront books but in 6 turns (budget 4); drip_fed never books in 8. NEXT: adaptive-reask-precision (harness), then no-coverage-symptom (harness), then queue #3 pending-booking-contract with clean instruments."
}
```
