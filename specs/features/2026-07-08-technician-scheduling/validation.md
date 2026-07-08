# Technician Scheduling (Tier 2) — Validation

## Automated
- [ ] Alembic rev 002 up/down clean on a fresh DB.
- [ ] Seed idempotent: `make seed` twice → identical row counts; all six specialties
      covered; 8 technicians across ≥ 5 zips.
- [ ] Concurrency race test: two bookings, one slot → exactly one `appointments` row,
      slot `booked`, loser receives `slot_taken`.
- [ ] Matching edge cases green (no-tech zip, wrong specialty, window filter).
- [ ] `make transcript` booking scenarios green — including: zip given during
      diagnostics is never re-asked at scheduling time.
- [ ] `make eval` green on the booking scenarios — Knowledge Retention catches any
      re-asked zip/availability; G-Eval confirmation rubric: technician + date + time
      read back and explicit yes received before booking.
      Required scenario set: `evals/scenarios/scheduling/*`; current known blockers
      from the 2026-07-08 real-key fixture run are `scheduling_happy_booking`,
      `scheduling_no_tech_in_zip`, and `scheduling_slot_conflict`.
- [ ] `make lint` + `make test` clean.

## Manual
1. Chat: "my dryer is broken, I'm in 60601, free Tuesday afternoon" → hear ≤ 3 real
   seeded options → confirm → agent reads back technician/date/time → yes → verbal
   confirmation with appointment id.
2. Inspect DB: `appointments` row present, slot flipped to `booked`.
3. Second session attempts the same slot → graceful alternative offer, no double book.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Deferred scope (reschedule/cancel, email confirmations) recorded in the roadmap
      backlog.
- [ ] Roadmap Phase 2 ticked `[x]`.
