"""Scheduling agent tools: ``find_technicians`` / ``book_appointment``.

Owned by the technician-scheduling feature (COORDINATION.md §3). Implements
``app.contracts.FindTechnicians`` / ``BookAppointment`` exactly (parameter names
and shapes are frozen). Exposed via the module-level ``TOOLS`` list picked up by
``app.tools.registry`` auto-discovery — adding a tool is adding a file, never
editing a shared registry.

Booking integrity (mission non-negotiable 4): ``book_appointment`` claims its
slot with a single ``UPDATE ... WHERE status='open' RETURNING`` inside the same
transaction as the appointment insert (Decision 1, requirements.md). Postgres
row-locks the target row for the duration of the UPDATE, so under concurrent
calls for the same slot exactly one transaction sees ``status='open'`` and
wins; the loser's predicate matches zero rows (rowcount 0) and the tool returns
``slot_taken`` with alternatives — no read-then-write race is possible.

Two stub-seam judgment calls, since the frozen tool signatures don't carry
everything the schema needs (see requirements.md's "no live agent required"
seam — pure Python/SQL against ``contracts.CaseFile``, no agent context object):

1. ``appointments.appliance_type`` (NOT NULL) has no dedicated parameter on
   ``book_appointment`` — it is inferred from ``issue_summary`` by keyword
   match against the six appliance types (the agent is expected to name the
   appliance in the summary it hands over, exactly as the read-back/confirm
   flow already requires). If inference fails, the tool returns a structured
   error asking for an appliance-naming summary rather than guessing.
2. ``appointments.session_id`` has no parameter either (the contract's
   ``book_appointment`` takes no session/case-file argument) — it is resolved from
   the ambient ``current_session_id`` ContextVar (``app.agent.state``), the same
   implicit-context pattern the visual tools use: both channels bind it around each
   tool invocation (web: ``app/agent/core.py``; phone: ``VoiceSession.bind``).
   Attribution must never break booking integrity (mission non-negotiable 4): when
   no session is bound, or the ``sessions`` row doesn't exist yet, the insert falls
   back to ``NULL`` and emits a ``booking.session_unattributed`` event
   (2026-07-09-booking-session-attribution).

This module deliberately does NOT use ``from __future__ import annotations``: the
``find_technicians`` / ``book_appointment`` signatures reference the ``Appliance`` and
``Customer`` contract types, and the LlamaIndex tool loop builds each tool's JSON schema
from those annotations. Stringized (deferred) annotations become unresolved forward refs
at schema-build time and raise ``PydanticUserError`` when the agent binds the tools, so
the annotations must stay real objects here.
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import get_case_file, get_session_id, set_offered_slots
from app.contracts import Appliance, Customer
from app.db.matching import find_alternative_slots, find_technician_matches, session_scope
from app.db.models_scheduling import Appointment, AvailabilitySlot, Technician
from app.obs import log_event

logger = logging.getLogger("app.tools.scheduling")

# A read/write mirror of the ``customers`` table owned by voice-diagnostic-core's
# rev 0001 migration (shape per that feature's requirements.md: id, name, phone,
# email, created_at). This feature does not create or migrate that table — only
# reads/writes rows in it via parameterized SQLAlchemy Core, exactly as it would
# via an ORM model, to satisfy ``appointments.customer_id``'s FK.
_customers_metadata = MetaData()
_customers_table = Table(
    "customers",
    _customers_metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("name", String(120)),
    Column("phone", String(20)),
    Column("email", String(255)),
    Column("created_at", DateTime(timezone=True)),
)

# Read-only mirror of the ``sessions`` table (owned by voice-diagnostic-core's rev
# 0001), same pattern as ``_customers_table``: only the column this module reads —
# the FK-existence check before attributing a booking to a session.
_sessions_table = Table(
    "sessions",
    _customers_metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
)

# Per-session short refs for the most recently offered slots
# (2026-07-09-slot-reference-robustness): live models pass `slot_1`-style ordinals
# instead of copying 36-char UUIDs, so `find_technicians` labels each offer with a
# `ref` and `book_appointment` resolves refs through this map. Keyed by the ambient
# session id (None = sessionless runs, e.g. the eval harness); each new offer for a
# session replaces its mapping. In-memory per process is correct for the demo
# topology — one app container serves a whole session.
_offered_slot_refs: dict[uuid.UUID | None, dict[str, str]] = {}


def _resolve_slot_reference(slot_id: str) -> str | None:
    """Map a non-UUID slot reference (`slot_2`, `2`, `option 2`) to the cached UUID.

    Returns None when the reference matches nothing — the caller reports a
    structured error pointing back at `find_technicians`."""
    refs = _offered_slot_refs.get(get_session_id())
    if not refs:
        return None
    normalized = slot_id.strip().lower().replace("option", "slot").replace(" ", "_")
    normalized = normalized.replace("slot#", "slot_").replace("#", "")
    if normalized.isdigit():
        normalized = f"slot_{normalized}"
    if not normalized.startswith("slot_") and normalized.startswith("slot"):
        normalized = f"slot_{normalized.removeprefix('slot')}"
    return refs.get(normalized)


_APPLIANCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "washer": ("washer", "washing machine"),
    "dryer": ("dryer",),
    "refrigerator": ("refrigerator", "fridge", "freezer"),
    "dishwasher": ("dishwasher", "dish washer"),
    "oven": ("oven", "stove", "range"),
    "hvac": (
        "hvac",
        "air conditioner",
        "air conditioning",
        "furnace",
        "heater",
        "a/c",
        " ac ",
        "thermostat",
    ),
}


def _require_customer_contact() -> bool:
    """Whether book_appointment enforces caller name+email (task #27).

    Default-ON; a live lane can pin it off (``BOOKING_REQUIRE_CONTACT=0``) while its
    caller persona is updated to collect an email, so the requirement never turns a
    green advisory gate red before its owner adjusts.
    """
    return os.environ.get("BOOKING_REQUIRE_CONTACT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


# Longest keyword first (T9): plain dict-order substring scan filed every
# "dishwasher" summary under washer ("dishwasher" contains "washer" and the
# washer entry came first). Sorting by keyword length makes the most specific
# alias win regardless of table order.
_KEYWORDS_BY_LENGTH: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            (keyword, appliance)
            for appliance, keywords in _APPLIANCE_KEYWORDS.items()
            for keyword in keywords
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)


def _infer_appliance_type(issue_summary: str) -> Appliance | None:
    text = f" {issue_summary.lower()} "
    for keyword, appliance in _KEYWORDS_BY_LENGTH:
        if keyword in text:
            return appliance  # type: ignore[return-value]
    return None


async def _resolve_session_id(session: AsyncSession, slot_id: str) -> uuid.UUID | None:
    """Resolve the booking's owning session from the ambient ContextVar, or ``None``.

    Attribution never blocks a booking (module docstring, judgment call 2): a missing
    binding or a not-yet-persisted ``sessions`` row degrades to ``NULL`` with a typed
    ``booking.session_unattributed`` event instead of an FK failure mid-transaction.
    """
    session_id = get_session_id()
    if session_id is None:
        log_event(logger, "booking.session_unattributed", reason="no_active_session", slot=slot_id)
        return None
    exists = (
        await session.execute(
            select(_sessions_table.c.id).where(_sessions_table.c.id == session_id)
        )
    ).first()
    if exists is None:
        log_event(
            logger,
            "booking.session_unattributed",
            reason="session_row_missing",
            slot=slot_id,
        )
        return None
    return session_id


async def _get_or_create_customer_id(session: AsyncSession, customer: Customer) -> uuid.UUID:
    if customer.email:
        existing = await session.execute(
            select(_customers_table.c.id).where(_customers_table.c.email == customer.email)
        )
        row = existing.first()
        if row is not None:
            return row[0]
    new_id = uuid.uuid4()
    await session.execute(
        insert(_customers_table).values(
            id=new_id,
            name=customer.name,
            phone=None,
            email=customer.email,
            created_at=datetime.now(UTC),
        )
    )
    return new_id


# Matching detail (kept out of the LLM-visible docstring — o13 schema slimming):
# service area must include `zip` AND specialties must include `appliance_type`; up to
# 3 soonest open future slots per technician, soonest technician first. The free-text
# `window` ("Tuesday afternoon", "tomorrow morning") narrows the slot choice when it
# matches but never hides all options — if nothing matches, soonest slots return anyway.
async def find_technicians(zip: str, appliance_type: Appliance, window: str | None = None) -> str:
    """Find technicians serving `zip` for `appliance_type`, up to 3 soonest open slots
    each; optional free-text `window` (e.g. "Tuesday afternoon") narrows when possible.
    Returns JSON {"status": "ok"|"no_technicians", "technicians": [{"technician_id",
    "name", "slots": [{"ref", "slot_id", "starts_at", "ends_at"}]}]}."""
    # Persist the zip we're searching with into the case file so later turns — notably
    # the booking-confirmation turn, whose system prompt is rebuilt from the case file
    # (app/agent/core.py Decision 4) — still have it. A zip passed only as this argument
    # is otherwise lost next turn, so the agent re-asks for the zip it just used and
    # never reaches book_appointment (task #21, live-observed 2026-07-10). Guarded for
    # sessionless/eval contexts where no case file is bound to the turn.
    try:
        get_case_file().customer.zip = zip
    except LookupError:
        pass
    async with session_scope() as session:
        matches = await find_technician_matches(
            session, zip_code=zip, appliance_type=appliance_type, window=window
        )

    if not matches:
        return json.dumps({"status": "no_technicians", "technicians": []})

    refs: dict[str, str] = {}
    offered: list[dict[str, str]] = []
    technicians_payload = []
    for match in matches:
        slots_payload = []
        for slot in match.slots:
            ref = f"slot_{len(refs) + 1}"
            refs[ref] = slot.slot_id
            slots_payload.append(
                {
                    "ref": ref,
                    "slot_id": slot.slot_id,
                    "starts_at": slot.starts_at.isoformat(),
                    "ends_at": slot.ends_at.isoformat(),
                }
            )
            offered.append(
                {
                    "ref": ref,
                    "technician": match.name,
                    "slot_id": slot.slot_id,
                    "starts_at": slot.starts_at.isoformat(),
                    "ends_at": slot.ends_at.isoformat(),
                }
            )
        technicians_payload.append(
            {
                "technician_id": match.technician_id,
                "name": match.name,
                "slots": slots_payload,
            }
        )
    _offered_slot_refs[get_session_id()] = refs
    # Retain the offered set so the next turn's system prompt can list these slots and the
    # model can book the one the caller accepts without re-searching (task #21). The
    # slot_id→UUID resolution still goes through _offered_slot_refs above; this store is
    # the prompt-visible, human-readable view of the same offer.
    set_offered_slots(get_session_id(), offered)
    return json.dumps({"status": "ok", "technicians": technicians_payload})


# Mechanics (kept out of the LLM-visible docstring — o13 schema slimming): the slot is
# claimed with a single conditional UPDATE inside the appointment insert's transaction
# (see module docstring) — double booking is impossible by construction.
async def book_appointment(slot_id: str, customer: Customer, issue_summary: str) -> str:
    """Atomically book a previously-offered slot — only after the caller verbally
    confirmed technician + date + time with an explicit yes. Pass the slot's `slot_id`
    or short `ref` verbatim from find_technicians. Returns JSON {"status": "confirmed",
    "appointment_id", "technician", "starts_at", "ends_at"} | {"status": "slot_taken",
    "alternatives": [...]} (re-offer them, never silently retry) | {"status": "error",
    "message"} (e.g. unknown slot id, or issue_summary doesn't name an appliance)."""
    if isinstance(customer, dict):
        # The LlamaIndex tool loop passes nested object args as raw dicts, not pydantic
        # models (live evidence 2026-07-09: every web-channel booking raised
        # `AttributeError: 'dict' object has no attribute 'email'`). Coerce at the tool
        # boundary; pydantic still validates the shape.
        customer = Customer(**customer)

    # Task #27: a real booking must carry the caller's name + email so the customers row
    # is contactable (live-observed: bookings landed with no email because the model
    # never persisted it). Sourced from the case file (the confirmed truth), falling back
    # to the passed arg. Enforced only when a case file is bound — i.e. an actual agent
    # turn; direct tool/unit calls (the slot-integrity tests) have no case file and are
    # exercising the claim path, not the contact policy, so they are untouched.
    if _require_customer_contact():
        try:
            case_file = get_case_file()
        except LookupError:
            case_file = None
        if case_file is not None:
            name = (case_file.customer.name or customer.name or "").strip()
            email = (case_file.customer.email or customer.email or "").strip()
            missing = [field for field, value in (("name", name), ("email", email)) if not value]
            if missing:
                log_event(logger, "booking.missing_contact", missing=",".join(missing))
                return json.dumps(
                    {
                        "status": "error",
                        "message": (
                            f"Missing the caller's {' and '.join(missing)}. Collect the "
                            'caller\'s name and email (spell the email back and get a "yes"), '
                            "save them with update_case_file, then call book_appointment "
                            "again."
                        ),
                    }
                )
            # Book under the confirmed case-file contact info.
            customer = Customer(name=name, email=email, zip=case_file.customer.zip or customer.zip)

    try:
        slot_uuid = uuid.UUID(slot_id)
    except (ValueError, AttributeError, TypeError):
        # Not a UUID: try the short refs from this session's latest offer
        # (2026-07-09-slot-reference-robustness — live models pass `slot_1`, not UUIDs).
        resolved = _resolve_slot_reference(slot_id) if isinstance(slot_id, str) else None
        if resolved is None:
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        f"'{slot_id}' is not a valid slot id. Pass the exact `slot_id` "
                        "or `ref` (like slot_1) returned by `find_technicians` — call "
                        "it again if you no longer have the list."
                    ),
                }
            )
        log_event(logger, "booking.slot_ref_resolved", ref=slot_id, slot=resolved)
        slot_uuid = uuid.UUID(resolved)

    appliance_type = _infer_appliance_type(issue_summary)
    if appliance_type is None:
        return json.dumps(
            {
                "status": "error",
                "message": (
                    "issue_summary must name the appliance (washer, dryer, "
                    "refrigerator, dishwasher, oven, or hvac/air conditioning) so "
                    "the appointment can be filed correctly."
                ),
            }
        )

    async with session_scope() as session:
        try:
            claim_stmt = (
                update(AvailabilitySlot)
                .where(AvailabilitySlot.id == slot_uuid, AvailabilitySlot.status == "open")
                .values(status="booked")
                .returning(
                    AvailabilitySlot.id,
                    AvailabilitySlot.technician_id,
                    AvailabilitySlot.starts_at,
                    AvailabilitySlot.ends_at,
                )
            )
            claimed = (await session.execute(claim_stmt)).first()

            if claimed is None:
                await session.rollback()
                tech_row = (
                    await session.execute(
                        select(AvailabilitySlot.technician_id).where(
                            AvailabilitySlot.id == slot_uuid
                        )
                    )
                ).first()
                if tech_row is None:
                    # A well-formed UUID that matches NO slot row: the model invented or
                    # mangled the id (live evidence 2026-07-09, booking-session-attribution
                    # manual gate). Reporting this as `slot_taken` misleads recovery —
                    # "no longer available" reads as bad luck, not a bad id — so name the
                    # real problem and the fix.
                    log_event(logger, "booking.unknown_slot_id", slot=slot_id)
                    return json.dumps(
                        {
                            "status": "error",
                            "message": (
                                f"No slot with id '{slot_id}' exists. Use the exact "
                                "`slot_id` returned by `find_technicians` — call it "
                                "again and copy the id of the chosen slot verbatim."
                            ),
                        }
                    )
                alt_slots = await find_alternative_slots(session, str(tech_row[0]))
                refs: dict[str, str] = {}
                alternatives = []
                for s in alt_slots:
                    ref = f"slot_{len(refs) + 1}"
                    refs[ref] = s.slot_id
                    alternatives.append(
                        {
                            "ref": ref,
                            "slot_id": s.slot_id,
                            "starts_at": s.starts_at.isoformat(),
                            "ends_at": s.ends_at.isoformat(),
                        }
                    )
                if refs:
                    _offered_slot_refs[get_session_id()] = refs
                return json.dumps({"status": "slot_taken", "alternatives": alternatives})

            claimed_slot_id, technician_id, starts_at, ends_at = claimed

            tech_row = (
                await session.execute(select(Technician.name).where(Technician.id == technician_id))
            ).first()
            technician_name = tech_row[0] if tech_row is not None else "Unknown"

            customer_id = await _get_or_create_customer_id(session, customer)
            session_id = await _resolve_session_id(session, slot_id)

            appointment_id = uuid.uuid4()
            await session.execute(
                insert(Appointment).values(
                    id=appointment_id,
                    slot_id=claimed_slot_id,
                    session_id=session_id,
                    customer_id=customer_id,
                    technician_id=technician_id,
                    appliance_type=appliance_type,
                    issue_summary=issue_summary,
                    status="confirmed",
                )
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return json.dumps(
        {
            "status": "confirmed",
            "appointment_id": str(appointment_id),
            "technician": technician_name,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        }
    )


TOOLS: list[object] = [find_technicians, book_appointment]
