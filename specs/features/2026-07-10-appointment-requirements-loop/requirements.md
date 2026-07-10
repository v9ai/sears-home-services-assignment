# Appointment Requirements Loop — Requirements

## Source

The take-home spec ("SHS Offshore AI Engineer Take-Home Project v8"), Tier 2
"Technician Scheduling" + Tier 1 "Conversation Memory", as mirrored in
`specs/features/2026-07-08-technician-scheduling/requirements.md`:

> Technician database (name, available zip codes, specialties, time slots) ·
> availability matching by zip + appliance · scheduling flow collecting customer
> availability and proposing matching technician time slots · verbal confirmation of
> the scheduled appointment details before concluding the call · seed 5–10
> technicians across multiple zips and specialties · maintain context; never re-ask
> information already provided.

## Problem

Tier 2 is substantially implemented, but nothing continuously checked the spec
requirements as a whole, and four measured gaps existed at loop start:

1. Confirmation read-back enforced only by prompt text + LLM rubric — no
   deterministic transcript check (the rubric lane is advisory and judge-key-gated).
2. No zip format validation (`String(10)` accepts anything; garbage zips silently
   match no technicians).
3. `book_appointment` infers `appliance_type` from `issue_summary` keywords only —
   booking errors when the summary lacks an appliance noun.
4. The phone channel does not thread offered slots into its prompt refresh
   (web-only), so phone bookings rely on the model re-holding context.
5. (Spec-ambiguous) street address is never captured — schema and CaseFile hold only
   a zip. Human decision, not a unilateral fix.

## The loop

`.claude/skills/appointment-requirements-iterate/SKILL.md` (frozen copy:
`loop-protocol.md` in this directory — on drift the committed copy wins). Metric:
`make appt-req` → `scripts/appointment_requirements_bench.py` → hermetic, keyless,
deterministic probes; report in `data/appt_req/` (gitignored, referenced by filename
from the ledger). Durable state: `loop-ledger.md` here.

## Spec matrix (requirement → probe → owning fix)

| Spec clause | Probe | Sub-check | Owning fix |
|---|---|---|---|
| Technician DB schema (technicians, service areas, specialties, availability, appointments) | `r_db_schema` | — | pre-existing (rev 0002); probe pins it |
| Seed 5–10+ techs, multiple zips/specialties | `r_seed` | — | pre-existing (`app/db/seed.py`); probe pins it |
| Availability matching by zip + appliance | `r_match` | — | pre-existing (`app/db/matching.py`); probe pins it |
| Scheduling flow: collect availability, propose matching slots (≤3) | `r_flow` | plain checks | pre-existing (`SCHEDULING_CONTRACT`); probe pins it |
| — zip input quality | `r_flow` | `zip_validation` | **f1** |
| — phone parity for offered slots | `r_flow` | `phone_offered_slots` | **f3** |
| Verbal confirmation before concluding | `r_confirm` | plain checks | pre-existing contract; probe pins it |
| — deterministic read-back transcript check | `r_confirm` | `readback_fixture` | **q2** |
| — explicit appliance on booking | `r_confirm` | `explicit_appliance_param` | **f2** |
| Never re-ask known facts (Tier 1) | `r_memory` | — | pre-existing; probe proves the detector fires |
| Live-DB conformance (seeded counts, live matching) | `db_live` | — | advisory lane, never gates |
| Street address capture | — | — | **h1** (decision packet) |

## Gates

`make appt-req` (soft until the terminal gate-flip earns `APPT_REQ_GATE_HARD`
default 1 and `test: stutter appt-req`), `make lint`, full `make test`,
`make eval-hermetic` for fixes touching `app/`/`evals/`.

## Coordination

The booking-quality loop (`specs/features/2026-07-10-booking-quality-loop/`, state
`running`) owns live conversation-quality tuning; this loop stays hermetic and off
its surfaces (`evals/adaptive_driver.py`, `scripts/booking_quality_bench.py`).
Shared-file appends (`Makefile`, `pyproject.toml`) are staged at hunk level under
the collaborator-dirt rule.
