# Booking session attribution — Validation

## Automated (only the gates this feature's surface triggers)
- [ ] `tests/scheduling/test_booking_session_attribution.py` — attributed booking
      writes `appointments.session_id`; missing `sessions` row → NULL + typed event +
      booking still confirmed; no bound session → NULL + typed event; probe returns
      True only for the booked session.                                      [logic changed]
- [ ] Voice: `ensure_voice_session_row` creates the row once, is idempotent, and a DB
      failure surfaces only as `voice.session_row.ensure_failed`.            [logic changed]
- [ ] Existing booking concurrency test still green (atomicity untouched).   [logic changed]
- [ ] `make lint` + `make test` clean; `make transcript` clean.              [code changed]

## Manual
1. `make up`, book via the web chat, then
   `SELECT id, session_id, appliance_type FROM appointments ORDER BY created_at DESC LIMIT 1`
   — `session_id` populated and equal to the chat session's id.
2. (With the phone channel live) one booked phone call → same query shows the
   `uuid5(CallSid)` session id; the recordings UI lists that session.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Not constitution-revising; `mission.md` / `tech-stack.md` untouched.
- [ ] Deferred scope (probe wiring into `make eval-live`) recorded in
      `specs/constitution/roadmap.md` / testing-evals group 7.
- [ ] Matching roadmap phase (Phase 11) ticked `[x]`.
