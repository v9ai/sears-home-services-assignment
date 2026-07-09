# Slot reference robustness (live Tier-2 booking) — Requirements

## Source
Pasted requirement (not from the roadmap):
> Live-run evidence (2026-07-09, gathered while closing the
> booking-session-attribution manual gate): the live web agent
> (`LLM_PROVIDER=openai`, `gpt-4.1-mini`) repeatedly failed to complete a booking —
> it called `book_appointment` with `slot_id='slot_1'` (an invented ordinal) instead
> of copying the 36-char UUID from `find_technicians`' JSON, looped on re-fetching
> slots, and never converged. A verbatim-copy prompt instruction did not fix it.
> The PDF's Tier-2 scheduling flow is unreliable live even though every offline
> gate (unit tests, fixtures, `make eval` 33/33) is green — fixtures can't catch it.

## Scope

### Included
- `find_technicians` labels every offered slot with a short **`ref`** (`slot_1`,
  `slot_2`, … in offer order across technicians) alongside the real UUID `slot_id`,
  and remembers the ref→UUID mapping per ambient session
  (`get_session_id()`-keyed module cache; `None` key supported so the eval harness
  works sessionless). Each new offer replaces the session's mapping. `slot_taken`
  alternatives are labelled + cached the same way.
- `book_appointment` resolves its `slot_id` argument through the mapping when it is
  not a UUID: exact `slot_N`, bare `N`, and `option N`/`option_N` normalize to the
  cached ref. UUIDs keep working unchanged (the mapping is a fallback, not a
  replacement). Unknown non-UUID references return the existing "use the exact
  slot_id / call find_technicians again" structured error.
- `SCHEDULING_CONTRACT` (prompt) tells the model it may pass either the exact
  `slot_id` or the slot's `ref` exactly as returned.
- Tests: ref resolution (slot_N / N / option N), per-session cache isolation, UUIDs
  still first-class, unknown ref → structured error, alternatives refresh the cache.

### Not included (deferred)
- Persisting the ref cache (in-memory per process is correct for the demo topology:
  one app container serves a whole session).
- Changing the frozen `BookAppointment` signature or the `slot_id` field name.
- The broader live-eval gate that would have caught this (`make eval-live`,
  testing-evals group 7).

### Contract shapes
- `find_technicians` JSON gains `"ref"` per slot — additive, no consumer removed;
  `book_appointment(slot_id: str, ...)` signature unchanged (resolution is internal).
- Source-of-truth file(s): `app/tools/scheduling_tools.py`, `app/agent/prompts.py`.
- Pipeline / build target: `make lint` · `make test` · `make transcript`.

## Decisions
1. **Meet the model's demonstrated behavior instead of fighting it** — the live model
   invents `slot_1` unprompted; short refs are what every production voice-agent
   scheduling interface converges on. Prompt-only mitigation was tried first and
   failed (evidence above).
2. **Ambient-session-keyed in-memory cache** — same `get_session_id()` context the
   attribution feature uses; no schema, no new dependency, correct for the
   single-process demo.
3. **UUID stays the canonical id** — refs are a resolution convenience; every payload
   still carries the real `slot_id`, so logs/tests/DB semantics are unchanged.
4. **Deploy path**: no deploy — server code + prompt.
5. **Gate path**: `make lint` + `make test` + `make transcript`; live adaptive booking
   drive must complete an attributed booking (manual evidence recorded in
   validation.md).

## Architecture impact
- Component / plane touched: scheduling tools + system prompt.
- **Invariant-preserving**: frozen tool signatures unchanged; booking atomicity
  untouched; additive payload field.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; discovered by and paired
  with `2026-07-09-booking-session-attribution/` (its manual gate is the live
  evidence driver).
- Constraints: no new abstraction; the conditional-UPDATE claim stays the only
  booking path.
- Open questions / explicit deferrals: none beyond "Not included".
