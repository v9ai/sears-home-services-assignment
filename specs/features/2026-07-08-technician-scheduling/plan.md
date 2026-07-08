# Technician Scheduling (Tier 2) — Plan

Implement in dependency order; the booking transaction (group 4) is the risky group —
run it alone and pause for review.

## 1. Schema
- [x] Alembic rev 002: six tables per requirements contract shapes; up/down verified on
      a fresh DB.

## 2. Seed
- [x] `app/db/seed.py`: 8 technicians, ~6 zips in two clusters, overlapping specialties
      covering all six appliance types, two-week rolling slots. Idempotent via natural
      keys (run twice → same row counts). `make seed`.

## 3. Matching
- [x] Matching query (service_areas ⋈ technician_specialties ⋈ open future slots,
      soonest first) + `find_technicians` tool returning ≤ 3 slots per technician.
- [x] Repo tests: zip with no technician; technician in zip with wrong specialty;
      window filtering. (`tests/scheduling/test_matching.py`)

## 4. Booking transaction                              ⏸ review after this group
- [x] `book_appointment`: atomic slot claim + appointment insert in one transaction;
      `slot_taken` path returns alternatives.
- [x] Concurrency test: two concurrent bookings race one slot → exactly one wins.
      (`tests/scheduling/test_booking.py::test_concurrent_booking_race_exactly_one_wins`,
      passed 5/5 repeated runs plus the full suite.)

## 5. Conversation flow
- [ ] System-prompt scheduling contract: offer after failed troubleshooting or on
      request; collect zip/availability case-file-first; read-back confirmation before
      booking; confirm appointment id verbally.
      **Not landed by this feature** — the system prompt lives in `app/agent/`,
      owned exclusively by voice-diagnostic-core (COORDINATION.md §3), and that
      feature's own requirements.md explicitly defers scheduling tools to Phase 2
      ("Scheduling tools — Phase 2"). Tool contracts + docstrings are ready for this
      wiring (see Integration deltas below for the exact prompt contract to add).

## 6. Gates
- [x] `make lint` + `make test` clean — verified directly (`ruff check`/`ruff format
      --check` + `pytest tests/scheduling`) since the `Makefile` `lint`/`test` target
      bodies are still foundation TODO stubs owned by testing-evals; nothing to wire
      here beyond what's already declared in Integration deltas.
- [ ] Extend `make transcript` with scenarios: happy booking · no-tech-in-zip ·
      slot-conflict recovery · zip captured earlier is never re-asked.
      **Not landed by this feature** — `scripts/transcript_runner.py` and
      `evals/scenarios/` are owned by testing-evals, whose own plan.md already lists
      these exact 4 scheduling scenarios. Tool JSON response shapes are documented in
      `app/tools/scheduling_tools.py` docstrings for that authoring.
- [ ] Extend `make eval`: booking scenarios through the DeepEval gate (Knowledge
      Retention; G-Eval confirmation rubric — read-back + explicit yes before booking).
      **Not landed by this feature** — same ownership note as above (`evals/`).
- [ ] Tick roadmap Phase 2 `[x]` in `specs/constitution/roadmap.md`.
      **Deferred** — Phase 2's Definition of Done (validation.md) requires the
      `make transcript` / `make eval` scheduling scenarios and the live conversation
      flow (group 5), neither of which this feature can land itself (see above); the
      lead should tick this once those integration steps land.

## Integration deltas (lead applies at merge)

1. **System prompt scheduling contract** (`app/agent/`, owned by voice-diagnostic-core)
   — add to the agent's system prompt once this feature's tools are auto-discovered:
   - Offer scheduling after troubleshooting fails to resolve the issue, or immediately
     if the caller asks to book a technician.
   - Before calling `find_technicians`, use the case file's `customer.zip` if already
     captured — never re-ask; only ask for zip/availability if genuinely missing.
   - Call `find_technicians(zip, appliance_type, window?)`; present ≤ 3 options
     (technician name + day/time) verbally.
   - Once the caller picks one, **read back technician name + date + time and get an
     explicit yes** before calling `book_appointment(slot_id, customer, issue_summary)`.
     `issue_summary` must name the appliance (washer/dryer/refrigerator/dishwasher/
     oven/hvac) — `book_appointment` infers `appliance_type` from it and returns a
     structured error if it can't (see `scheduling_tools.py` docstring).
   - On `{"status":"slot_taken"}`, apologize and re-offer `alternatives` — never retry
     silently.
   - On `{"status":"confirmed"}`, read back the `appointment_id` to the caller.
2. **`make seed` target body** (`Makefile`, owned by testing-evals per the foundation
   stub comment) — wire to `python -m app.db.seed` (idempotent; entry point already
   implemented and tested in `app/db/seed.py`).
3. **`evals/scenarios/` scheduling scenarios** (owned by testing-evals, already
   anticipated in that feature's own plan.md) — the 4 scheduling scenarios can be
   authored directly against `find_technicians`/`book_appointment`'s documented JSON
   response shapes; no additional contract needed from this feature.
4. **Test placement note**: this feature's own verification tests live under the new
   `tests/scheduling/` subdirectory (own `conftest.py`/factories — the shared
   `tests/conftest.py` owned by testing-evals was not touched). `pyproject.toml`'s
   `testpaths = ["tests"]` already picks these up recursively; no Makefile change is
   needed for `make test` to include them once its body is wired to run `pytest`.
5. **Alembic merge revision**: this feature's rev `0002_scheduling` was verified
   up/down-clean locally against a throwaway, uncommitted stub `0001_core` revision
   (customers/sessions tables only, shape per voice-diagnostic-core's requirements.md)
   since the real `0001_core` doesn't exist in this worktree — per COORDINATION.md §2
   this is expected; the lead should re-verify `alembic upgrade heads` once the real
   `0001_core` merges, then add the merge revision.
6. **Known limitation**: `appointments.session_id` is always `NULL` from
   `book_appointment` — the frozen `BookAppointment` protocol takes no session/case-file
   argument, so there's no way for this tool to know the calling session's id. If the
   live agent should have appointments traceable to their originating session, the
   integration step should either extend the calling convention (not the frozen
   signature) or accept this as a recorded gap.
