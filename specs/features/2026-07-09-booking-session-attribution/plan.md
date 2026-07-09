# Booking session attribution — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups. This is booking logic — the risky group (3) runs solo.

## 3. Pipeline / logic change                          [if pipeline change]
- [x] `app/tools/scheduling_tools.py` — add a `_sessions_table` read-mirror (same
      pattern as `_customers_table`); in `book_appointment`, resolve
      `get_session_id()` → verify the `sessions` row exists inside the booking
      transaction → write it, or fall back to NULL + `booking.session_unattributed`
      event (`reason=no_active_session|session_row_missing`). Rewrite the stub-seam
      docstring note 2.
- [x] `app/voice/recording.py` — `ensure_voice_session_row(session)`: get-or-create the
      minimal phone `sessions` row; best-effort with `voice.session_row.ensure_failed`
      event on error.
- [x] `app/voice/bot.py` `_on_connected` — fire `ensure_voice_session_row` as a held
      background task (off the greeting critical path).
- [x] `app/voice/tools.py` — correct the `book_appointment` bridge comment (the
      contextvar read + start-row is the real mechanism).
- [x] `evals/live_driver.py` — add `appointments_booking_probe()` returning a
      `BookingProbe` that SELECTs an `appointments` row by `session_id`.

## 5. Gates
- [x] New `tests/scheduling/test_booking_session_attribution.py` green (attributed /
      missing-row fallback / no-session fallback / probe).
- [x] Voice-side test for `ensure_voice_session_row` idempotence green.
- [x] `make lint` + `make test` clean; `make transcript` clean.

## 6. Deploy                                           [if deploy in scope]
- [x] No deploy. Record as roadmap Phase 11; tick `[x]` when the DoD holds. Manual DB
      check: one web-chat booking → `SELECT session_id FROM appointments` populated.
