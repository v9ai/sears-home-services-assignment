# Technician Scheduling (Tier 2) — Requirements

## Source
Roadmap Phase 2 (specs/constitution/roadmap.md). Assignment Tier 2:
> Technician database (name, available zip codes, specialties, time slots) · availability
> matching by zip + appliance · scheduling flow collecting customer availability ·
> verbal confirmation before concluding · seed 5–10 technicians across multiple zips and
> specialties.

## Scope

### Included
- Alembic rev 002: the scheduling schema below.
- Idempotent seed (`make seed`): **8 technicians** across ~6 zip codes in two metro
  clusters, overlapping specialties covering all six appliance types, two-week rolling
  slot horizon.
- Matching by zip + appliance type: SQL join over service areas × specialties × open
  future slots, soonest first.
- Scheduling conversation wired into the Phase 1 agent: offer scheduling after failed
  troubleshooting or on request; collect zip and availability window (case file first —
  never re-ask); offer ≤ 3 slots; read-back confirmation; book.
- Appointment persistence + verbal and text confirmation with the appointment id.

### Not included (deferred)
- Reschedule / cancel flows — backlog (tool sketch only).
- Email confirmations — lands with Tier 3's email infrastructure.
- Geo-radius matching, travel time, real calendars, technician-side UI.

### Contract shapes
- Alembic rev 002:
  - `technicians(id, name, phone, email, employment_type text CHECK IN
    ('full_time','contractor') DEFAULT 'full_time', hired_on date, active bool
    DEFAULT true)` — identity, contact info, and employment details per the
    assignment's schema minimum.
  - `specialties(id, name)` — seeded exactly with the six appliance types, FK-aligned
    with the `appliance_type` enum values.
  - `technician_specialties(technician_id FK, specialty_id FK, PK(both))`
  - `service_areas(technician_id FK, zip_code varchar(10), PK(both), INDEX(zip_code))`
  - `availability_slots(id, technician_id FK, starts_at timestamptz, ends_at timestamptz,
    status text CHECK IN ('open','booked') DEFAULT 'open',
    UNIQUE(technician_id, starts_at))`
  - `appointments(id, slot_id FK UNIQUE, session_id FK, customer_id FK,
    technician_id FK, appliance_type, issue_summary text,
    status text CHECK IN ('confirmed','cancelled') DEFAULT 'confirmed', created_at)`
- Agent tools:
  - `find_technicians(zip, appliance_type, window?) → [{technician, slots[≤3]}]`
  - `book_appointment(slot_id, customer, issue_summary) → confirmation | slot_taken`
- Seed source of truth: `app/db/seed.py`. Gates: `make test`, `make transcript`,
  `make eval`.

## Decisions
1. **Atomic slot claim** — `UPDATE availability_slots SET status='booked'
   WHERE id=:id AND status='open' RETURNING id` inside the appointment-insert
   transaction; rowcount 0 → tool returns `slot_taken` and the agent apologizes and
   re-offers. Double booking is impossible by construction (mission non-negotiable 4).
2. **Specialties as a lookup + junction table, not a CSV column** — the assignment
   explicitly grades schema thinking; junction tables show it and keep the specialty
   domain extensible (e.g. install vs repair) without touching technicians.
3. **Slots as pre-generated rows, not recurrence rules** — simpler queries, honest for a
   two-week demo horizon; recurrence generation recorded as deferred.
4. **Exact-zip matching, no geo radius** — a SQL join is transparent and testable;
   radius search deferred.
5. **Mandatory read-back confirmation** — the prompt contract requires technician name +
   date + time read back and an explicit yes before `book_appointment` is called.
6. **Gate path**: pytest (incl. concurrency race), `make transcript` booking scenarios,
   `make eval` (Knowledge Retention on zip/availability; G-Eval booking-confirmation
   rubric).

## Architecture impact
- Extends the DB plane (rev 002) and the Phase 1 agent's tool registry.
  Invariant-preserving.

## Parallel execution (COORDINATION.md §3–4)
- Owned paths: `app/tools/scheduling_tools.py`, `app/db/models_scheduling.py`,
  `app/db/seed.py`, `app/db/matching.py`, `alembic/versions/0002_scheduling*`.
- Stub seam: tools + schema are pure Python/SQL against `contracts.CaseFile`; fully
  testable with pytest + the Compose `db`, no agent required. Tool file is
  auto-discovered at integration — no shared-file edits.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; builds on the Phase 1
  session/case-file shapes (`2026-07-08-voice-diagnostic-core/requirements.md`).
- Constraints: never-re-ask (zip captured earlier must not be asked again); no raw SQL
  interpolation; Alembic only.
- Open question (deferred): whether `window` filtering is a hard filter or a soft
  ordering preference when few slots match.
