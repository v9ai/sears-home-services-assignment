"""Booking session attribution (2026-07-09-booking-session-attribution).

``book_appointment`` resolves the ambient ``current_session_id`` ContextVar into
``appointments.session_id`` — with a NULL fallback + typed
``booking.session_unattributed`` event whenever attribution would break the booking
(no bound session, or the ``sessions`` FK-target row doesn't exist yet). The
conftest's isolated scheduling DB already declares the minimal ``sessions``
stand-in, so these tests exercise the real FK.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import select

from app.agent.state import current_session_id
from app.contracts import Customer
from app.db.matching import session_scope
from app.db.models_scheduling import Appointment
from app.db.models_scheduling import Base as SchedulingBase
from app.tools.scheduling_tools import book_appointment
from evals.live_driver import appointments_booking_probe

from .factories import make_slot, make_technician

_SESSIONS = SchedulingBase.metadata.tables["sessions"]
_EVENT_LOGGER = "app.tools.scheduling"


async def _seed_open_slot() -> uuid.UUID:
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()
    return slot_id


async def _insert_session_row(session_id: uuid.UUID) -> None:
    async with session_scope() as session:
        await session.execute(sa.insert(_SESSIONS).values(id=session_id))
        await session.commit()


async def _booked_appointment(slot_id: uuid.UUID) -> Appointment:
    async with session_scope() as session:
        return (
            await session.execute(select(Appointment).where(Appointment.slot_id == slot_id))
        ).scalar_one()


async def test_booking_attributed_to_bound_session():
    slot_id = await _seed_open_slot()
    session_id = uuid.uuid4()
    await _insert_session_row(session_id)

    token = current_session_id.set(session_id)
    try:
        result = json.loads(
            await book_appointment(str(slot_id), Customer(name="Jamie Rivera"), "Washer won't spin")
        )
    finally:
        current_session_id.reset(token)

    assert result["status"] == "confirmed"
    appt = await _booked_appointment(slot_id)
    assert appt.session_id == session_id


async def test_missing_session_row_falls_back_to_null_with_event(caplog):
    """A bound session whose row isn't persisted yet (e.g. a hypothetical turn-1 web
    booking) must degrade to NULL + event — never an FK failure that loses the booking."""
    slot_id = await _seed_open_slot()
    session_id = uuid.uuid4()  # deliberately NO sessions row

    token = current_session_id.set(session_id)
    try:
        with caplog.at_level(logging.INFO, logger=_EVENT_LOGGER):
            result = json.loads(
                await book_appointment(
                    str(slot_id), Customer(name="Jamie Rivera"), "Washer won't spin"
                )
            )
    finally:
        current_session_id.reset(token)

    assert result["status"] == "confirmed"
    appt = await _booked_appointment(slot_id)
    assert appt.session_id is None
    assert any(
        "event=booking.session_unattributed" in r.message
        and "reason=session_row_missing" in r.message
        for r in caplog.records
    )


async def test_no_bound_session_falls_back_to_null_with_event(caplog):
    slot_id = await _seed_open_slot()

    token = current_session_id.set(None)
    try:
        with caplog.at_level(logging.INFO, logger=_EVENT_LOGGER):
            result = json.loads(
                await book_appointment(
                    str(slot_id), Customer(name="Jamie Rivera"), "Washer won't spin"
                )
            )
    finally:
        current_session_id.reset(token)

    assert result["status"] == "confirmed"
    appt = await _booked_appointment(slot_id)
    assert appt.session_id is None
    assert any(
        "event=booking.session_unattributed" in r.message
        and "reason=no_active_session" in r.message
        for r in caplog.records
    )


async def test_appointments_booking_probe_matches_only_the_booked_session():
    slot_id = await _seed_open_slot()
    session_id = uuid.uuid4()
    await _insert_session_row(session_id)

    token = current_session_id.set(session_id)
    try:
        result = json.loads(
            await book_appointment(str(slot_id), Customer(name="Jamie Rivera"), "Washer won't spin")
        )
    finally:
        current_session_id.reset(token)
    assert result["status"] == "confirmed"

    probe = appointments_booking_probe()
    assert await probe(session_id) is True
    assert await probe(uuid.uuid4()) is False
    assert await probe(None) is False
