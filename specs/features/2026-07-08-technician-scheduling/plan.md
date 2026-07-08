# Technician Scheduling (Tier 2) — Plan

Implement in dependency order; the booking transaction (group 4) is the risky group —
run it alone and pause for review.

## 1. Schema
- [ ] Alembic rev 002: six tables per requirements contract shapes; up/down verified on
      a fresh DB.

## 2. Seed
- [ ] `app/db/seed.py`: 8 technicians, ~6 zips in two clusters, overlapping specialties
      covering all six appliance types, two-week rolling slots. Idempotent via natural
      keys (run twice → same row counts). `make seed`.

## 3. Matching
- [ ] Matching query (service_areas ⋈ technician_specialties ⋈ open future slots,
      soonest first) + `find_technicians` tool returning ≤ 3 slots per technician.
- [ ] Repo tests: zip with no technician; technician in zip with wrong specialty;
      window filtering.

## 4. Booking transaction                              ⏸ review after this group
- [ ] `book_appointment`: atomic slot claim + appointment insert in one transaction;
      `slot_taken` path returns alternatives.
- [ ] Concurrency test: two concurrent bookings race one slot → exactly one wins.

## 5. Conversation flow
- [ ] System-prompt scheduling contract: offer after failed troubleshooting or on
      request; collect zip/availability case-file-first; read-back confirmation before
      booking; confirm appointment id verbally.

## 6. Gates
- [ ] Extend `make transcript` with scenarios: happy booking · no-tech-in-zip ·
      slot-conflict recovery · zip captured earlier is never re-asked.
- [ ] `make lint` + `make test` clean.
- [ ] Tick roadmap Phase 2 `[x]` in `specs/constitution/roadmap.md`.
