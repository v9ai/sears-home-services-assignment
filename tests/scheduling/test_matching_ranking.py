"""Ranking, multi-technician, and no-slots edge cases for ``find_technician_matches``.

Runs against the isolated per-test scheduling database (tests/scheduling/conftest.py
gives each test a freshly-created ``public`` schema — never repo ``data/`` or the
app's real database).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.matching import find_technician_matches, session_scope

from .factories import make_slot, make_technician


async def test_multiple_qualifying_technicians_ordered_by_name():
    """Both technicians serve the zip/appliance; results come back name-ascending
    (the query's primary sort), independent of who owns the soonest slot."""
    async with session_scope() as session:
        now = datetime.now(UTC)
        zoe = await make_technician(
            session, name="Zoe Adams", zips=("60601",), specialties=("washer",)
        )
        amy = await make_technician(
            session, name="Amy Barnes", zips=("60601",), specialties=("washer",)
        )
        # Zoe holds the *earliest* slot — name ordering must still put Amy first.
        await make_slot(session, zoe, now + timedelta(days=1))
        await make_slot(session, amy, now + timedelta(days=2))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")

    assert [m.name for m in matches] == ["Amy Barnes", "Zoe Adams"]


async def test_multi_zip_technician_matches_each_served_zip_and_no_other():
    async with session_scope() as session:
        now = datetime.now(UTC)
        tech = await make_technician(
            session, name="Ravi Shah", zips=("60601", "60614"), specialties=("dryer",)
        )
        await make_slot(session, tech, now + timedelta(days=1))
        await session.commit()

        in_first = await find_technician_matches(session, "60601", "dryer")
        in_second = await find_technician_matches(session, "60614", "dryer")
        uncovered = await find_technician_matches(session, "60642", "dryer")

    assert [m.name for m in in_first] == ["Ravi Shah"]
    assert [m.name for m in in_second] == ["Ravi Shah"]
    assert uncovered == []


async def test_specialty_subset_matches_only_declared_appliances():
    async with session_scope() as session:
        now = datetime.now(UTC)
        tech = await make_technician(
            session, name="Lee Ng", zips=("60601",), specialties=("washer", "dryer")
        )
        await make_slot(session, tech, now + timedelta(days=1))
        await session.commit()

        washer = await find_technician_matches(session, "60601", "washer")
        dryer = await find_technician_matches(session, "60601", "dryer")
        oven = await find_technician_matches(session, "60601", "oven")

    assert [m.name for m in washer] == ["Lee Ng"]
    assert [m.name for m in dryer] == ["Lee Ng"]
    assert oven == []


async def test_qualifying_technician_with_no_open_future_slots_is_absent():
    """Zip + specialty match, but every slot is in the past or already booked —
    the caller must not be offered a technician with nothing to book."""
    async with session_scope() as session:
        now = datetime.now(UTC)
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech, now - timedelta(days=1))  # past
        await make_slot(session, tech, now + timedelta(days=1), status="booked")  # taken
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")

    assert matches == []


async def test_each_technician_capped_at_three_soonest_slots():
    async with session_scope() as session:
        now = datetime.now(UTC)
        a = await make_technician(
            session, name="Amy Barnes", zips=("60601",), specialties=("washer",)
        )
        b = await make_technician(
            session, name="Zoe Adams", zips=("60601",), specialties=("washer",)
        )
        for tech in (a, b):
            for days in (4, 1, 5, 2, 3):
                await make_slot(session, tech, now + timedelta(days=days))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")

    assert len(matches) == 2
    for m in matches:
        assert len(m.slots) == 3
        starts = [s.starts_at for s in m.slots]
        assert starts == sorted(starts)  # soonest-first within each technician


async def test_window_narrows_slots_but_keeps_all_qualifying_technicians():
    async with session_scope() as session:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        a = await make_technician(
            session, name="Amy Barnes", zips=("60601",), specialties=("washer",)
        )
        b = await make_technician(
            session, name="Zoe Adams", zips=("60601",), specialties=("washer",)
        )
        # Each has one morning and one afternoon slot.
        for tech in (a, b):
            await make_slot(session, tech, tomorrow.replace(hour=9))
            await make_slot(session, tech, tomorrow.replace(hour=14))
        await session.commit()

        matches = await find_technician_matches(
            session, "60601", "washer", window="tomorrow morning"
        )

    assert [m.name for m in matches] == ["Amy Barnes", "Zoe Adams"]
    for m in matches:
        assert len(m.slots) == 1
        assert m.slots[0].starts_at.hour == 9
