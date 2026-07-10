# Booking quality loop — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups.

## 3. Pipeline / logic change                          [if pipeline change]
- [x] `evals/adaptive_driver.py` — `AdaptiveScenario`, `reply_policy` (deterministic
      keyword state machine), `drive_adaptive(scenario, *, llm, session_id)` looping
      `run_turn`, reusing `detect_reasks` + `appointments_booking_probe`.
- [x] `scripts/booking_quality_bench.py` — six-scenario matrix, signature-preserving
      tool wiretap (call/result capture incl. the out-of-band `slot_conflict`
      pre-book), scoring vs pinned targets, JSON report + `--compare`, self-cleanup
      `finally` block, exit code.
- [x] `Makefile` — `booking-bench` target.
- [x] `.claude/skills/booking-quality-iterate/SKILL.md` — the /loop-driven iteration
      protocol (§1 preconditions … §8 stop/continue) with the seeded fix queue.
- [x] `loop-ledger.md` bootstrap (state: ready, iteration: 0).

## 5. Gates
- [x] Hermetic: `tests/test_booking_quality_policy.py` (policy decision table,
      scoring, report shape, compare) green with no DB/LLM.
- [x] `make lint` + `make test` clean.
- [x] One keyed smoke run of `make booking-bench` completes, writes a report, leaves
      the DB clean (row counts identical before/after) — harness proof, not the
      loop's official baseline (iteration 1 owns that).

## 6. Deploy                                           [if deploy in scope]
- [ ] No deploy. Roadmap Phase 12 entry added; ticked only when the loop reaches a
      terminal state (`stopped (success|dry|exhausted|cost-cap)`) with the ledger as
      evidence.
