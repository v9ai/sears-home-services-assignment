# Booking session attribution — Requirements

## Source
Pasted requirement (not from the roadmap):
> Gap analysis vs the assignment PDF (2026-07-09): `appointments.session_id` is always
> NULL. `book_appointment` (`app/tools/scheduling_tools.py`) hardcodes
> `session_id=None` and never reads `get_session_id()` — while the comment at
> `app/voice/tools.py` (phone bridge) claims running inside `session.bind()` "closes
> the session_id=None gap". Bookings are unattributable to the call that made them on
> BOTH channels, weakening the Tier-2 booking-integrity story and the Tier-3 session
> linkage the schema was designed for.

## Scope

### Included
- `book_appointment` reads the ambient `get_session_id()` ContextVar
  (`app/agent/state.py`) at booking time and writes it to `appointments.session_id`.
  The frozen `BookAppointment` contract signature is NOT widened — this is the same
  implicit-context pattern the visual tools already use (`app/tools/visual_tools.py`).
- **Attribution never breaks booking integrity**: if no session id is bound, or the
  `sessions` row does not exist yet (FK target), the insert falls back to
  `session_id=NULL` and emits a typed `booking.session_unattributed` observability
  event (`app/obs.py:log_event`) with a `reason` field — the booking itself always
  proceeds.
- **Phone channel FK ordering**: the phone `sessions` row is currently written only at
  disconnect (`persist_voice_session`), so a mid-call attributed insert would find no
  FK target. New `ensure_voice_session_row` (in `app/voice/recording.py`, next to
  `persist_voice_session`) inserts the minimal row (`id=uuid5(call_sid)`,
  `channel='phone'`, `call_sid`) at call start, fired from `_on_connected` in
  `app/voice/bot.py` as a background task (never delays the greeting; failure logged,
  never breaks the call). `persist_voice_session` (call end) remains the owner of the
  full row update — its existing get-or-create upsert is unchanged.
- The misleading "closes the session_id=None gap" comment in `app/voice/tools.py` and
  the stale "Always NULL" stub-seam note in `scheduling_tools.py`'s docstring are
  rewritten to describe the real mechanism.
- `evals/live_driver.py` gains `appointments_booking_probe()` — a ready-made
  `BookingProbe` that asserts a real `appointments` row exists for the driven
  `session_id` (the harness's `booking_row` assert stops being inferable-only).
- Tests (`tests/scheduling/test_booking_session_attribution.py`): attributed booking
  (bound session + existing row → `session_id` populated), missing-row fallback
  (bound session, no `sessions` row → NULL + event, booking still confirmed),
  no-session fallback (nothing bound → NULL + event), and the existing concurrency
  guarantee untouched. Voice-side: `ensure_voice_session_row` inserts once and is
  idempotent.

### Not included (deferred)
- Wiring `appointments_booking_probe` into `make transcript` / `make eval-live` runs —
  that belongs to the testing-evals group 7 live-gate implementation (the probe is the
  building block it was spec'd to use).
- Backfilling `session_id` on historical appointment rows (demo DB, no value).
- Web-channel first-turn edge: the web `sessions` row commits after turn 1, so a
  hypothetical turn-1 booking falls back to NULL by design (bookings require
  zip + appliance + confirmation, so this cannot occur in a real flow).

### Contract shapes
- Data touched: `appointments.session_id` (nullable FK → `sessions.id`, rev
  `0002_scheduling`) — no schema change; the column finally gets written.
- Source-of-truth file(s): `app/tools/scheduling_tools.py`,
  `app/voice/recording.py`, `app/voice/bot.py`, `app/voice/tools.py`,
  `evals/live_driver.py`.
- Pipeline / build target: `make lint` · `make test` (scheduling suite needs a
  reachable `DATABASE_URL` Postgres) · `make transcript`.

## Decisions
1. **ContextVar read, not signature widening** — the frozen `BookAppointment` contract
   stays byte-identical to `app/contracts.py`; the ambient-session pattern already
   sanctioned for visual tools extends to booking. (The old comment claimed widening
   was the only path and was wrong.)
2. **NULL-fallback + typed event over hard failure** — mission non-negotiable 4
   (booking integrity) outranks attribution; an unattributable booking is a logged
   observability event (`booking.session_unattributed`, `reason=
   no_active_session|session_row_missing`), never a lost booking.
3. **Row-at-call-start via a background task** — the phone greeting path stays off the
   DB critical path (latency budgets); `uuid5(CallSid)` determinism means the start-row
   and end-of-call upsert converge on the same PK with get-or-create on both sides.
4. **Deploy path**: no deploy — server code + tests.
5. **Gate path**: `make lint` + `make test` + `make transcript`; manual DB check of an
   attributed booking.

## Architecture impact
- Component / plane touched: scheduling tool, voice call lifecycle, eval harness
  helper.
- **Invariant-preserving**: no contract shape, schema, or constitution bullet changes;
  booking atomicity (conditional UPDATE claim) untouched.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md` (parameterized SQLAlchemy
  only; observability event core `app/obs.py`); scheduling test isolation pattern in
  `tests/scheduling/conftest.py` (dedicated `<db>_test_scheduling` database with
  `sessions`/`customers` stand-ins already declared).
- Constraints: booking transaction stays single-transaction atomic; no new
  abstraction; `session_scope()` usage unchanged.
- Open questions / explicit deferrals: none beyond "Not included".
