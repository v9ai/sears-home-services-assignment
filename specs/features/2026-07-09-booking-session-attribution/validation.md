# Booking session attribution — Validation

## Automated (only the gates this feature's surface triggers)
- [x] `tests/scheduling/test_booking_session_attribution.py` — attributed booking
      writes `appointments.session_id`; missing `sessions` row → NULL + typed event +
      booking still confirmed; no bound session → NULL + typed event; probe returns
      True only for the booked session.                                      [logic changed]
- [x] Voice: `ensure_voice_session_row` creates the row once, is idempotent, and a DB
      failure surfaces only as `voice.session_row.ensure_failed`.            [logic changed]
- [x] Existing booking concurrency test still green (atomicity untouched).   [logic changed]
- [x] `make lint` + `make test` clean; `make transcript` clean.              [code changed]

## Manual
1. `make up`, book via the web chat, then
   `SELECT id, session_id, appliance_type FROM appointments ORDER BY created_at DESC LIMIT 1`
   — `session_id` populated and equal to the chat session's id.
   — **RUN 2026-07-09 (equivalent in-process evidence): PASS.** Adaptive live drive
   through the real agent (`run_turn`, real OpenAI key, compose DB) with a seeded
   `sessions` row: booking confirmed and the `appointments` row carried that exact
   session id (see `2026-07-09-slot-reference-robustness/validation.md` for the full
   run — closing this gate live is what surfaced the three booking defects that
   feature fixes).
2. (With the phone channel live) one booked phone call → same query shows the
   `uuid5(CallSid)` session id; the recordings UI lists that session. — **Owed**:
   needs the real-handset window (roadmap Phase 5); the phone-side mechanism is
   covered hermetically by `tests/voice/test_session_row.py`.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Not constitution-revising; `mission.md` / `tech-stack.md` untouched.
- [x] Deferred scope (probe wiring into `make eval-live`) recorded in
      `specs/constitution/roadmap.md` / testing-evals group 7.
- [x] Matching roadmap phase (Phase 11) ticked `[x]`.
