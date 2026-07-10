"""Timezone and slot-boundary edge cases for the matcher.

The slot columns are ``DateTime(timezone=True)`` and the matcher compares against
an explicit ``now`` (``AvailabilitySlot.starts_at > now``) and against the
half-open ``[window_start, window_end)`` produced by ``parse_window``. These
tests pin ``now`` so the ``>`` / ``>=`` / ``<`` boundaries are deterministic, and
confirm a slot written with a non-UTC offset is stored and returned as the same
instant. Runs against the isolated per-test scheduling database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.db.matching import find_alternative_slots, find_technician_matches, session_scope

from .factories import make_slot, make_technician


async def test_slot_starting_exactly_at_now_is_excluded_next_instant_included():
    """The future filter is strict (``> now``): a slot whose start equals the
    reference instant is in the past-or-present and must not be offered."""
    now = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    async with session_scope() as session:
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech, now)  # exactly now — excluded
        just_after = await make_slot(session, tech, now + timedelta(seconds=1))
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer", now=now)

    assert len(matches) == 1
    assert [s.slot_id for s in matches[0].slots] == [str(just_after)]


async def test_daypart_end_hour_is_excluded_start_hour_is_included():
    """``parse_window`` yields a half-open interval: a 12:00 slot is *afternoon*,
    never *morning* (end is exclusive), and it is the first *afternoon* slot
    (start is inclusive)."""
    now = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)
    eleven = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)  # morning
    noon = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)  # afternoon boundary
    async with session_scope() as session:
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech, eleven)
        await make_slot(session, tech, noon)
        await session.commit()

        morning = await find_technician_matches(
            session, "60601", "washer", window="morning", now=now
        )
        afternoon = await find_technician_matches(
            session, "60601", "washer", window="afternoon", now=now
        )

    # Morning window [06:00, 12:00): 11:00 in, 12:00 out (end exclusive).
    assert [s.starts_at.hour for s in morning[0].slots] == [11]
    # Afternoon window [12:00, 17:00): 12:00 in (start inclusive), 11:00 out.
    assert [s.starts_at.hour for s in afternoon[0].slots] == [12]


async def test_slot_written_with_non_utc_offset_round_trips_as_same_instant():
    """A slot persisted with a ``-04:00`` offset is the same absolute instant as
    its UTC equivalent; the matcher must compare instants (not wall-clock) and
    return a timezone-aware value."""
    minus_four = timezone(timedelta(hours=-4))
    local_instant = datetime(2026, 7, 16, 8, 0, tzinfo=minus_four)  # == 12:00 UTC
    now = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
    async with session_scope() as session:
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech, local_instant)
        await session.commit()

        matches = await find_technician_matches(session, "60601", "washer", now=now)

    assert len(matches) == 1
    returned = matches[0].slots[0].starts_at
    assert returned.utcoffset() is not None  # timezone-aware, not naive
    assert returned == local_instant  # same instant regardless of stored offset
    assert returned.astimezone(UTC).hour == 12


async def test_window_that_lands_entirely_in_the_past_falls_back_to_soonest():
    """A morning window requested at 3pm resolves to a past interval that matches
    no future slot; the soft-preference fallback must still surface the tech's
    real upcoming slots rather than an empty list."""
    now = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)  # 3pm — past this morning
    async with session_scope() as session:
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        evening = await make_slot(session, tech, now.replace(hour=18))
        await session.commit()

        matches = await find_technician_matches(
            session, "60601", "washer", window="morning", now=now
        )

    assert len(matches) == 1
    assert [s.slot_id for s in matches[0].slots] == [str(evening)]


async def test_alternative_slots_use_the_same_strict_future_boundary():
    now = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    async with session_scope() as session:
        tech = await make_technician(session, zips=("60601",), specialties=("washer",))
        await make_slot(session, tech, now)  # exactly now — excluded
        upcoming = await make_slot(session, tech, now + timedelta(hours=2))
        await session.commit()

        alts = await find_alternative_slots(session, str(tech), now=now)

    assert [a.slot_id for a in alts] == [str(upcoming)]
