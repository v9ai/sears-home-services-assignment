"""Booking-integrity coverage: record linkage, customer de-duplication, slot
consumption, alternatives, and an N-way concurrent race.

Runs against the isolated per-test scheduling database (tests/scheduling/conftest.py).
``book_appointment`` is exercised through its real tool entry point, so these
tests cover the UPDATE...WHERE status='open' RETURNING claim path end to end.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.contracts import Customer
from app.db.matching import find_alternative_slots, find_technician_matches, session_scope
from app.db.models_scheduling import Appointment, AvailabilitySlot
from app.tools.scheduling_tools import book_appointment

from .factories import make_slot, make_technician


async def test_appointment_links_slot_technician_and_customer():
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

    async with session_scope() as session:
        appt = (
            await session.execute(select(Appointment).where(Appointment.slot_id == slot_id))
        ).scalar_one()
        assert str(appt.slot_id) == str(slot_id)
        assert str(appt.technician_id) == str(tech_id)
        assert appt.appliance_type == "washer"
        assert appt.customer_id is not None
        # The customer_id resolves to the row created from the caller's details.
        email = (
            await session.execute(
                text("SELECT email FROM customers WHERE id = :id"),
                {"id": str(appt.customer_id)},
            )
        ).scalar_one()
        assert email == "jamie@example.test"


async def test_repeat_customer_email_is_deduplicated_across_bookings():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        now = datetime.now(UTC)
        slot_a = await make_slot(session, tech_id, now + timedelta(days=1))
        slot_b = await make_slot(session, tech_id, now + timedelta(days=2))
        await session.commit()

    customer = Customer(name="Sam Repeat", zip="60601", email="sam@example.test")
    for slot in (slot_a, slot_b):
        r = json.loads(await book_appointment(str(slot), customer, "Washer leaking"))
        assert r["status"] == "confirmed"

    async with session_scope() as session:
        customer_ids = (await session.execute(select(Appointment.customer_id))).scalars().all()
    assert len(customer_ids) == 2
    assert len(set(customer_ids)) == 1  # same customer row reused via email


async def test_booking_without_email_creates_distinct_customers():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        now = datetime.now(UTC)
        slot_a = await make_slot(session, tech_id, now + timedelta(days=1))
        slot_b = await make_slot(session, tech_id, now + timedelta(days=2))
        await session.commit()

    for slot in (slot_a, slot_b):
        r = json.loads(
            await book_appointment(str(slot), Customer(name="Anonymous Caller"), "Washer broken")
        )
        assert r["status"] == "confirmed"

    async with session_scope() as session:
        customer_ids = (await session.execute(select(Appointment.customer_id))).scalars().all()
    assert len(set(customer_ids)) == 2  # no email to dedupe on


async def test_booked_slot_is_no_longer_offered_by_matching():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    r = json.loads(
        await book_appointment(str(slot_id), Customer(name="Jamie"), "Washer won't spin")
    )
    assert r["status"] == "confirmed"

    async with session_scope() as session:
        matches = await find_technician_matches(session, "60601", "washer")
    assert matches == []  # the only slot is consumed


async def test_appliance_type_inferred_from_summary_synonyms():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("refrigerator",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    r = json.loads(
        await book_appointment(str(slot_id), Customer(name="Jamie"), "the fridge stopped cooling")
    )
    assert r["status"] == "confirmed"

    async with session_scope() as session:
        appt = (
            await session.execute(select(Appointment).where(Appointment.slot_id == slot_id))
        ).scalar_one()
        assert appt.appliance_type == "refrigerator"


async def test_sequential_double_booking_is_rejected():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("dryer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    first = json.loads(
        await book_appointment(str(slot_id), Customer(name="First"), "Dryer not heating")
    )
    second = json.loads(
        await book_appointment(str(slot_id), Customer(name="Second"), "Dryer not heating")
    )

    assert first["status"] == "confirmed"
    assert second["status"] == "slot_taken"

    async with session_scope() as session:
        count = len(
            (await session.execute(select(Appointment).where(Appointment.slot_id == slot_id)))
            .scalars()
            .all()
        )
    assert count == 1


async def test_five_way_concurrent_race_yields_exactly_one_confirmation():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("dryer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

    results = await asyncio.gather(
        *(
            book_appointment(str(slot_id), Customer(name=f"Caller {i}"), "Dryer not heating")
            for i in range(5)
        )
    )
    statuses = sorted(json.loads(r)["status"] for r in results)
    assert statuses == ["confirmed", "slot_taken", "slot_taken", "slot_taken", "slot_taken"]

    async with session_scope() as session:
        slot = (
            await session.execute(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
        ).scalar_one()
        assert slot.status == "booked"
        appts = (
            (await session.execute(select(Appointment).where(Appointment.slot_id == slot_id)))
            .scalars()
            .all()
        )
    assert len(appts) == 1


async def test_find_alternative_slots_excludes_booked_and_past_and_respects_limit():
    async with session_scope() as session:
        now = datetime.now(UTC)
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech_id, now - timedelta(days=1))  # past — excluded
        await make_slot(session, tech_id, now + timedelta(days=1), status="booked")  # taken
        open_slots = [
            await make_slot(session, tech_id, now + timedelta(days=d)) for d in (2, 3, 4, 5)
        ]
        await session.commit()

        alts = await find_alternative_slots(session, str(tech_id), limit=3)

    assert len(alts) == 3  # limit honored
    returned = [a.slot_id for a in alts]
    assert returned == [str(open_slots[0]), str(open_slots[1]), str(open_slots[2])]  # soonest first
    starts = [a.starts_at for a in alts]
    assert starts == sorted(starts)


async def test_booking_a_nonexistent_slot_uuid_reports_error_not_slot_taken():
    result = json.loads(
        await book_appointment(str(uuid.uuid4()), Customer(name="Ghost"), "Washer broken")
    )
    assert result["status"] == "error"
    assert "find_technicians" in result["message"]
