# Slot reference robustness (live Tier-2 booking) — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups. Booking logic — the risky group runs solo.

## 3. Pipeline / logic change                          [if pipeline change]
- [ ] `app/tools/scheduling_tools.py` — per-session ref cache
      (`_offered_slot_refs`, keyed by `get_session_id()`); `find_technicians` adds
      `"ref": "slot_N"` per offered slot and stores the mapping;
      `book_appointment` resolves non-UUID `slot_id` via `_resolve_slot_reference`
      (`slot_N` / `N` / `option N`); `slot_taken` alternatives refresh the cache.
- [ ] `app/agent/prompts.py` `SCHEDULING_CONTRACT` — the model may pass the exact
      `slot_id` or the slot's `ref`.

## 5. Gates
- [ ] New tests in `tests/scheduling/test_slot_references.py` green.
- [ ] `tests/test_prompts_scheduling.py` updated + green.
- [ ] `make lint` + `make test` clean; `make transcript` clean.
- [ ] Live adaptive booking drive completes an ATTRIBUTED booking (evidence in
      validation.md).

## 6. Deploy                                           [if deploy in scope]
- [ ] No deploy. Recorded with Phase 11 in `specs/constitution/roadmap.md`.
