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
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import get_session_id
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


def _infer_appliance_type(issue_summary: str) -> Appliance | None:
    text = f" {issue_summary.lower()} "
    for appliance, keywords in _APPLIANCE_KEYWORDS.items():
        for keyword in keywords:
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


async def find_technicians(zip: str, appliance_type: Appliance, window: str | None = None) -> str:
    """Find qualified technicians in a zip code with open slots.

    Matches technicians whose service area includes ``zip`` and whose
    specialties include ``appliance_type``, returning up to 3 soonest open
    future slots per technician (soonest technician first). ``window`` is an
    optional free-text availability hint (e.g. "Tuesday afternoon",
    "tomorrow morning"); it narrows the slot choice when it matches, but never
    hides all options — if nothing matches the window, the soonest slots are
    returned anyway. Returns a JSON string:
    ``{"status": "ok"|"no_technicians", "technicians": [{"technician_id",
    "name", "slots": [{"slot_id", "starts_at", "ends_at"}]}]}``.
    """
    async with session_scope() as session:
        matches = await find_technician_matches(
            session, zip_code=zip, appliance_type=appliance_type, window=window
        )

    if not matches:
        return json.dumps({"status": "no_technicians", "technicians": []})

    technicians_payload = [
        {
            "technician_id": match.technician_id,
            "name": match.name,
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "starts_at": slot.starts_at.isoformat(),
                    "ends_at": slot.ends_at.isoformat(),
                }
                for slot in match.slots
            ],
        }
        for match in matches
    ]
    return json.dumps({"status": "ok", "technicians": technicians_payload})


async def book_appointment(slot_id: str, customer: Customer, issue_summary: str) -> str:
    """Atomically book a previously-offered slot. Call only after the caller has
    verbally confirmed technician + date + time with an explicit yes.

    Claims the slot with a single conditional UPDATE inside the appointment
    insert's transaction (see module docstring) — double booking is impossible
    by construction. Returns a JSON string:
    ``{"status": "confirmed", "appointment_id", "technician", "starts_at",
    "ends_at"}`` on success, or
    ``{"status": "slot_taken", "alternatives": [...]}`` if the slot was claimed
    by someone else first — apologize and re-offer the alternatives, do not
    retry silently. ``{"status": "error", "message"}`` on a bad request (e.g.
    unrecognized slot id, or an ``issue_summary`` that doesn't name an
    appliance).
    """
    try:
        slot_uuid = uuid.UUID(slot_id)
    except (ValueError, AttributeError, TypeError):
        return json.dumps({"status": "error", "message": f"'{slot_id}' is not a valid slot id."})

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
                alternatives: list[dict[str, str]] = []
                if tech_row is not None:
                    alt_slots = await find_alternative_slots(session, str(tech_row[0]))
                    alternatives = [
                        {
                            "slot_id": s.slot_id,
                            "starts_at": s.starts_at.isoformat(),
                            "ends_at": s.ends_at.isoformat(),
                        }
                        for s in alt_slots
                    ]
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
