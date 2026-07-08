from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.contracts import Customer
from app.db.matching import session_scope
from app.db.models_scheduling import Appointment, AvailabilitySlot
from app.tools.scheduling_tools import book_appointment

from .factories import make_slot, make_technician


async def test_book_appointment_confirms_and_claims_slot():
    async with session_scope() as session:
        tech_id = await make_technician(
            session, name="Ava Chen", zips=("60601",), specialties=("washer",)
        )
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    result = json.loads(
        await book_appointment(
            str(slot_id),
            Customer(name="Jamie Rivera", zip="60601", email="jamie@example.test"),
            "Washer won't spin, error code E1",
        )
    )

    assert result["status"] == "confirmed"
    assert result["technician"] == "Ava Chen"
    assert "appointment_id" in result

    async with session_scope() as session:
        slot = (
            await session.execute(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
        ).scalar_one()
        assert slot.status == "booked"

        appt = (
            await session.execute(select(Appointment).where(Appointment.slot_id == slot_id))
        ).scalar_one()
        assert appt.status == "confirmed"
        assert appt.appliance_type == "washer"
        assert str(appt.id) == result["appointment_id"]


async def test_book_appointment_slot_already_booked_returns_alternatives():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        taken_slot = await make_slot(
            session, tech_id, datetime.now(UTC) + timedelta(days=1), status="booked"
        )
        alt_slot = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=2))
        await session.commit()

    result = json.loads(
        await book_appointment(
            str(taken_slot), Customer(name="Jamie Rivera"), "Washer leaking water"
        )
    )

    assert result["status"] == "slot_taken"
    assert str(alt_slot) in [a["slot_id"] for a in result["alternatives"]]


async def test_book_appointment_bad_slot_id():
    result = json.loads(
        await book_appointment("not-a-uuid", Customer(name="Jamie Rivera"), "Washer broken")
    )
    assert result["status"] == "error"


async def test_book_appointment_requires_appliance_in_summary():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    result = json.loads(
        await book_appointment(str(slot_id), Customer(name="Jamie Rivera"), "It's broken")
    )
    assert result["status"] == "error"

    # The slot must remain open — a rejected request must not claim it.
    async with session_scope() as session:
        slot = (
            await session.execute(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
        ).scalar_one()
        assert slot.status == "open"


async def test_concurrent_booking_race_exactly_one_wins():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("dryer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    results = await asyncio.gather(
        book_appointment(str(slot_id), Customer(name="Caller A"), "Dryer not heating"),
        book_appointment(str(slot_id), Customer(name="Caller B"), "Dryer not heating"),
    )
    statuses = sorted(json.loads(r)["status"] for r in results)
    assert statuses == ["confirmed", "slot_taken"]

    async with session_scope() as session:
        slot = (
            await session.execute(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
        ).scalar_one()
        assert slot.status == "booked"

        appointments = (
            (await session.execute(select(Appointment).where(Appointment.slot_id == slot_id)))
            .scalars()
            .all()
        )
        assert len(appointments) == 1
