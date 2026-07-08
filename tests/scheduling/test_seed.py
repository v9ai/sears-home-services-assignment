from __future__ import annotations

from sqlalchemy import func, select

from app.db.matching import session_scope
from app.db.models_scheduling import (
    APPLIANCE_TYPES,
    AvailabilitySlot,
    ServiceArea,
    Specialty,
    Technician,
)
from app.db.seed import TECHNICIANS, seed


async def test_seed_is_idempotent_and_covers_scope():
    await seed()

    async with session_scope() as session:
        tech_count = (
            await session.execute(select(func.count()).select_from(Technician))
        ).scalar_one()
        specialty_names = set((await session.execute(select(Specialty.name))).scalars().all())
        zip_count = (
            await session.execute(select(func.count(func.distinct(ServiceArea.zip_code))))
        ).scalar_one()
        slot_count_1 = (
            await session.execute(select(func.count()).select_from(AvailabilitySlot))
        ).scalar_one()

    assert tech_count == len(TECHNICIANS) == 8
    assert specialty_names == set(APPLIANCE_TYPES)
    assert zip_count >= 5

    await seed()

    async with session_scope() as session:
        tech_count_2 = (
            await session.execute(select(func.count()).select_from(Technician))
        ).scalar_one()
        slot_count_2 = (
            await session.execute(select(func.count()).select_from(AvailabilitySlot))
        ).scalar_one()

    assert tech_count_2 == tech_count
    assert slot_count_2 == slot_count_1
