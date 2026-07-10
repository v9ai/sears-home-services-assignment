# Booking Quality Loop Ledger
state: ready
iteration: 0
bench_runs_total: 0
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
