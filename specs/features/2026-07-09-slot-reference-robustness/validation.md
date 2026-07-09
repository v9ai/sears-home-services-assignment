# Slot reference robustness (live Tier-2 booking) — Validation

## Automated (only the gates this feature's surface triggers)
- [x] `tests/scheduling/test_slot_references.py` — ref resolution (`slot_N`/`N`/
      `option N`), session isolation, UUID passthrough, unknown ref → structured
      error, alternatives refresh.                                          [logic changed]
- [x] `tests/test_prompts_scheduling.py` green with the ref wording.        [logic changed]
- [x] `make lint` + `make test` clean; `make transcript` clean.             [code changed]

## Manual
1. Adaptive live booking drive (real agent + seeded DB + bound session): the
   conversation converges to `book_appointment` → `{"status":"confirmed"}` and the
   `appointments` row carries the bound `session_id`.
   — **RUN 2026-07-09 (gpt-4.1-mini, real OpenAI key, compose DB): PASS in 2 turns.**
   `find_technicians` offered `slot_1..3`; the model called
   `book_appointment(slot_id='slot_1', customer=<dict>)`; ref resolved to the real
   UUID, dict coerced, result `{"status":"confirmed", "appointment_id":"2405a21a-…"}`,
   and the `appointments` row carried the seeded session id (`f1824e08-…`). Before
   the three fixes, five consecutive drives failed (invented UUID → misleading
   `slot_taken` → `AttributeError` on the dict customer); demo rows cleaned up after
   the run.
2. Spoken offers still read naturally (technician names/times, not refs) — confirmed
   in the same run's transcript.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Not constitution-revising; `mission.md` / `tech-stack.md` untouched.
- [x] Deferred scope (live-eval gate) recorded — already tracked as testing-evals
      group 7.
- [x] Matching roadmap phase (Phase 11, shared with booking-session-attribution)
      ticked `[x]`.
