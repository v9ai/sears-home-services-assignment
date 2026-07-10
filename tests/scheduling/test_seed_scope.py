"""Deeper seed coverage: exact slot counts, per-table idempotency, and
assignment-scope guarantees (every appliance covered, every technician staffed).

Complements ``test_seed.py`` (top-line idempotency + scope). Runs against the
isolated per-test scheduling database (tests/scheduling/conftest.py).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.matching import find_technician_matches, session_scope
from app.db.models_scheduling import (
    APPLIANCE_TYPES,
    AvailabilitySlot,
    ServiceArea,
    Specialty,
    Technician,
    TechnicianSpecialty,
)
from app.db.seed import SLOT_HORIZON_DAYS, SLOT_HOURS_UTC, TECHNICIANS, seed


async def _counts() -> dict[str, int]:
    async with session_scope() as session:

        async def count(model) -> int:
            return (await session.execute(select(func.count()).select_from(model))).scalar_one()

        return {
            "technicians": await count(Technician),
            "specialties": await count(Specialty),
            "technician_specialties": await count(TechnicianSpecialty),
            "service_areas": await count(ServiceArea),
            "slots": await count(AvailabilitySlot),
        }


async def test_slot_count_matches_horizon_formula():
    await seed()
    counts = await _counts()
    expected_slots = len(TECHNICIANS) * SLOT_HORIZON_DAYS * len(SLOT_HOURS_UTC)
    assert counts["slots"] == expected_slots  # 8 * 14 * 4 == 448


async def test_second_seed_leaves_every_table_count_unchanged():
    await seed()
    first = await _counts()
    await seed()
    second = await _counts()
    assert first == second  # junctions, service areas, and slots all stable


async def test_every_appliance_type_has_at_least_one_technician():
    await seed()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Specialty.name, func.count(TechnicianSpecialty.technician_id))
                .join(TechnicianSpecialty, TechnicianSpecialty.specialty_id == Specialty.id)
                .group_by(Specialty.name)
            )
        ).all()
    covered = {name for name, cnt in rows if cnt > 0}
    assert set(APPLIANCE_TYPES) <= covered


async def test_every_technician_is_staffed_with_specialties_and_service_areas():
    await seed()
    async with session_scope() as session:
        techs_with_specialty = (
            await session.execute(
                select(func.count(func.distinct(TechnicianSpecialty.technician_id)))
            )
        ).scalar_one()
        techs_with_area = (
            await session.execute(select(func.count(func.distinct(ServiceArea.technician_id))))
        ).scalar_one()
    assert techs_with_specialty == len(TECHNICIANS)
    assert techs_with_area == len(TECHNICIANS)


async def test_seed_covers_at_least_five_distinct_zip_codes():
    await seed()
    async with session_scope() as session:
        distinct_zips = (
            await session.execute(select(func.count(func.distinct(ServiceArea.zip_code))))
        ).scalar_one()
    assert distinct_zips >= 5


async def test_reseed_does_not_duplicate_matchable_slots():
    """A second seed must not double a technician's offered slots — the matcher
    caps at three, so this checks the underlying rows aren't duplicated by
    re-running (each of the 4 daily hours is distinct, none re-inserted)."""
    await seed()
    await seed()
    async with session_scope() as session:
        # 60601 + washer is served by two seeded technicians (Ava Chen, Diego Ruiz).
        matches = await find_technician_matches(session, "60601", "washer")
    names = sorted(m.name for m in matches)
    assert names == ["Ava Chen", "Diego Ruiz"]
    for m in matches:
        assert len(m.slots) == 3  # capped, and not inflated by the re-seed
        starts = [s.starts_at for s in m.slots]
        assert len(set(starts)) == 3  # distinct slot times, no duplicate rows
