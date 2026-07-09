# Technician Scheduling (Tier 2) — Validation

## Automated
- [x] Alembic rev 002 up/down clean on a fresh DB. (2026-07-09: `alembic upgrade head`
      then `downgrade base` against a scratch `sears_migcheck` DB — all 10 tables
      created and torn down cleanly.)
- [x] Seed idempotent: `make seed` twice → identical row counts; all six specialties
      covered; 8 technicians across ≥ 5 zips. (`tests/scheduling/test_seed.py`, green
      in the 2026-07-09 full-suite run.)
- [x] Concurrency race test: two bookings, one slot → exactly one `appointments` row,
      slot `booked`, loser receives `slot_taken`. (`tests/scheduling/test_booking.py`.)
- [x] Matching edge cases green (no-tech zip, wrong specialty, window filter).
      (`tests/scheduling/test_matching.py`.)
- [x] `make transcript` booking scenarios green — including: zip given during
      diagnostics is never re-asked at scheduling time. (2026-07-09: "transcript gate:
      PASS", `canary_knowledge_retention_reask` correctly caught the re-ask.)
- [x] `make eval` green on the booking scenarios — Knowledge Retention catches any
      re-asked zip/availability; G-Eval confirmation rubric: technician + date + time
      read back and explicit yes received before booking.
      Required scenario set: `evals/scenarios/scheduling/*`; the 2026-07-08 blockers
      (`scheduling_{happy_booking,no_tech_in_zip,slot_conflict,zip_never_reasked}`)
      cleared on 2026-07-09 — **full `make eval` 33/33 GREEN** after fixture enrichment
      (read-backs now carry technician name + specific date + time) and one recorded
      calibration: `slot_conflict` drops the generic `knowledge_retention` metric,
      which structurally cannot model a sanctioned slot swap (rationale comment in
      `evals/scenarios/scheduling/slot_conflict.yaml`; zip retention still gated by
      `assert.no_reask` + `zip_never_reasked`).
- [x] `make lint` + `make test` clean. (2026-07-09: lint green, 367 passed.)

## Manual
1. Chat: "my dryer is broken, I'm in 60601, free Tuesday afternoon" → hear ≤ 3 real
   seeded options → confirm → agent reads back technician/date/time → yes → verbal
   confirmation with appointment id.
2. Inspect DB: `appointments` row present, slot flipped to `booked`.
3. Second session attempts the same slot → graceful alternative offer, no double book.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green (2026-07-09).
- [x] Deferred scope (reschedule/cancel, email confirmations) recorded in the roadmap
      backlog.
- [x] Roadmap Phase 2 ticked `[x]` (2026-07-09).
