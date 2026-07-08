"""Minimal row-builders for scheduling tests — no dependency on `app/db/seed.py`
(which has its own idempotency tests) so each test controls its own fixture data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_scheduling import (
    AvailabilitySlot,
    ServiceArea,
    Specialty,
    Technician,
    TechnicianSpecialty,
)


async def make_technician(
    session: AsyncSession,
    *,
    name: str = "Test Tech",
    email: str | None = None,
    zips: tuple[str, ...] = ("60601",),
    specialties: tuple[str, ...] = ("washer",),
    active: bool = True,
) -> uuid.UUID:
    tech_id = uuid.uuid4()
    session.add(
        Technician(
            id=tech_id,
            name=name,
            phone="555-000-0000",
            email=email or f"{tech_id}@example.test",
            employment_type="full_time",
            hired_on=date(2022, 1, 1),
            active=active,
        )
    )
    await session.flush()
    for zip_code in zips:
        session.add(ServiceArea(technician_id=tech_id, zip_code=zip_code))
    await session.flush()
    for specialty_name in specialties:
        specialty_id = await _get_or_create_specialty(session, specialty_name)
        session.add(TechnicianSpecialty(technician_id=tech_id, specialty_id=specialty_id))
    await session.flush()
    return tech_id


async def _get_or_create_specialty(session: AsyncSession, name: str) -> uuid.UUID:
    from sqlalchemy import select

    existing = (await session.execute(select(Specialty.id).where(Specialty.name == name))).first()
    if existing is not None:
        return existing[0]
    specialty_id = uuid.uuid4()
    session.add(Specialty(id=specialty_id, name=name))
    await session.flush()
    return specialty_id


async def make_slot(
    session: AsyncSession,
    technician_id: uuid.UUID,
    starts_at: datetime,
    *,
    ends_at: datetime | None = None,
    status: str = "open",
) -> uuid.UUID:
    from datetime import timedelta

    slot_id = uuid.uuid4()
    session.add(
        AvailabilitySlot(
            id=slot_id,
            technician_id=technician_id,
            starts_at=starts_at,
            ends_at=ends_at or (starts_at + timedelta(hours=2)),
            status=status,
        )
    )
    await session.flush()
    return slot_id
