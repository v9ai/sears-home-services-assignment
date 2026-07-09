# Slot reference robustness (live Tier-2 booking) — Validation

## Automated (only the gates this feature's surface triggers)
- [ ] `tests/scheduling/test_slot_references.py` — ref resolution (`slot_N`/`N`/
      `option N`), session isolation, UUID passthrough, unknown ref → structured
      error, alternatives refresh.                                          [logic changed]
- [ ] `tests/test_prompts_scheduling.py` green with the ref wording.        [logic changed]
- [ ] `make lint` + `make test` clean; `make transcript` clean.             [code changed]

## Manual
1. Adaptive live booking drive (real agent + seeded DB + bound session): the
   conversation converges to `book_appointment` → `{"status":"confirmed"}` and the
   `appointments` row carries the bound `session_id`. Record the run here.
2. Confirm every `find_technicians` spoken offer still reads naturally (refs are for
   the tool layer; the agent speaks names/times, not refs).

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Not constitution-revising; `mission.md` / `tech-stack.md` untouched.
- [ ] Deferred scope (live-eval gate) recorded — already tracked as testing-evals
      group 7.
- [ ] Matching roadmap phase (Phase 11, shared with booking-session-attribution)
      ticked `[x]`.
