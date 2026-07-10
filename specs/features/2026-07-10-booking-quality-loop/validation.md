# Booking quality loop — Validation

## Automated (only the gates this feature's surface triggers)
- [x] `tests/test_booking_quality_policy.py` green (hermetic: policy table, scoring,
      report shape, compare).                                               [logic changed]
- [x] `make lint` + `make test` clean (550 passed; one format drift in a parallel session's in-flight scripts/latency_bench.py noted, not this feature's surface).                                      [code changed]

## Manual
1. Keyed smoke: `make booking-bench` runs the six scenarios against the real agent,
   writes `data/booking_quality/<ts>.json`, prints the per-scenario PASS/FAIL table,
   and leaves the dev DB byte-identical (appointments/customers/sessions counts and
   slot statuses unchanged). Record the run + `overall_pass` here.
   — **RUN 2026-07-10 (gpt-4.1-mini, report `2026-07-10T01-14-37Z.json`): harness
   PASS, agent 2/6.** DB counts identical before/after (`0 0 13 480`). The bench
   immediately reproduced the live defect class: `happy_upfront` booked but in 6
   turns (budget 4), `drip_fed`/`reask_trap` never converged (incl. a reproduced
   `customer.zip` re-ask), `no_coverage` + `slot_conflict` PASS (honest gap
   handling; slot_taken recovery works), and `safety_interrupt` FAILED —
   `safety_flag` never set on the web path after a mid-call gas mention (new
   finding, exactly what the loop's DIAGNOSE step should chase first).
   `tool_exceptions=0`, `unknown_ids=0` — the Phase 11 fixes hold live.
2. Read the report next to the transcript excerpts it embeds — per-scenario failure
   reasons must be actionable (they are what the loop's DIAGNOSE step ranks).
3. Launch check: `/loop /booking-quality-iterate` starts iteration 1, which archives
   the official baseline and commits the loop bootstrap.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Not constitution-revising; `mission.md` / `tech-stack.md` untouched.
- [x] Deferred scope (phone-channel drives, model-default decision, target changes)
      recorded above.
- [ ] Roadmap Phase 12 added; ticked only at the loop's terminal state.
