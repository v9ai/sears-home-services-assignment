from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.matching import find_technician_matches, parse_window, session_scope

from .factories import make_slot, make_technician


async def test_no_technician_in_zip():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

        matches = await find_technician_matches(session, "99999", "washer")
    assert matches == []


async def test_technician_in_zip_wrong_specialty():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("oven",))
        await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")
    assert matches == []


async def test_matching_returns_up_to_three_soonest_slots():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        now = datetime.now(UTC)
        # Five future slots — only the 3 soonest should come back.
        for days in (5, 1, 3, 2, 4):
            await make_slot(session, tech_id, now + timedelta(days=days))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")

    assert len(matches) == 1
    assert len(matches[0].slots) == 3
    starts = [s.starts_at for s in matches[0].slots]
    assert starts == sorted(starts)


async def test_inactive_technician_excluded():
    async with session_scope() as session:
        tech_id = await make_technician(
            session, zips=("60601",), specialties=("washer",), active=False
        )
        await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=1))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer")
    assert matches == []


async def test_window_filters_to_matching_day_part():
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        morning_slot = await make_slot(session, tech_id, tomorrow.replace(hour=9))
        await make_slot(session, tech_id, tomorrow.replace(hour=14))
        await session.commit()

        matches = await find_technician_matches(
            session, "60601", "washer", window="tomorrow morning"
        )

    assert len(matches) == 1
    assert [s.slot_id for s in matches[0].slots] == [str(morning_slot)]


async def test_window_soft_fallback_when_nothing_matches():
    """A window that matches nothing falls back to the unfiltered soonest slots
    (Decision, requirements.md open question resolved: soft preference)."""
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=("60601",), specialties=("washer",))
        now = datetime.now(UTC)
        only_slot = await make_slot(session, tech_id, (now + timedelta(days=1)).replace(hour=20))
        await session.commit()

        # No evening slots requested, only slot is at 20:00 (evening) -- request morning.
        matches = await find_technician_matches(
            session, "60601", "washer", window="tomorrow morning"
        )

    assert len(matches) == 1
    assert [s.slot_id for s in matches[0].slots] == [str(only_slot)]


def test_parse_window_none_is_unfiltered():
    assert parse_window(None) == (None, None)
    assert parse_window("") == (None, None)
    assert parse_window("no idea, whenever works") == (None, None)


def test_parse_window_weekday_and_daypart():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)  # a Wednesday
    start, end = parse_window("Friday afternoon", now=now)
    assert start is not None and end is not None
    assert start.weekday() == 4  # Friday
    assert start.hour == 12
    assert end.hour == 17
