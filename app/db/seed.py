"""Idempotent technician/slot seed (`make seed` per tech-stack.md; the Makefile
target body itself is an Integration delta — see plan.md — since ``Makefile`` is
not in this feature's ownership map).

8 technicians across 6 zip codes in two metro clusters (Chicago: 60601 / 60614 /
60642; Dallas: 75201 / 75204 / 75225), overlapping specialties covering all six
appliance types, and a two-week rolling slot horizon (4 slots/day: 09:00, 11:00,
13:00, 15:00 UTC) starting tomorrow.

Idempotent via natural keys: technician ``email`` is unique (ON CONFLICT DO
NOTHING); ``specialties.name`` is unique; the junction tables use their
composite primary keys; ``availability_slots`` uses UNIQUE(technician_id,
starts_at). Running ``python -m app.db.seed`` twice yields identical row
counts.

Run: ``python -m app.db.seed``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.matching import get_engine, session_scope
from app.db.models_scheduling import (
    APPLIANCE_TYPES,
    AvailabilitySlot,
    Base,
    ServiceArea,
    Specialty,
    Technician,
    TechnicianSpecialty,
)

SLOT_HORIZON_DAYS = 14
SLOT_HOURS_UTC = (9, 11, 13, 15)
SLOT_DURATION_HOURS = 2


@dataclass(frozen=True)
class TechnicianSeed:
    name: str
    phone: str
    email: str
    employment_type: str
    hired_on: date
    zips: tuple[str, ...]
    specialties: tuple[str, ...]


# Two metro clusters, overlapping specialties/zips per requirements.md Decision 2/4.
TECHNICIANS: tuple[TechnicianSeed, ...] = (
    TechnicianSeed(
        "Ava Chen",
        "312-555-0101",
        "ava.chen@searshs.example",
        "full_time",
        date(2021, 3, 1),
        ("60601", "60614"),
        ("washer", "dryer"),
    ),
    TechnicianSeed(
        "Marcus Bell",
        "312-555-0102",
        "marcus.bell@searshs.example",
        "contractor",
        date(2022, 6, 15),
        ("60601", "60642"),
        ("refrigerator", "dishwasher"),
    ),
    TechnicianSeed(
        "Priya Nair",
        "312-555-0103",
        "priya.nair@searshs.example",
        "full_time",
        date(2020, 11, 3),
        ("60614", "60642"),
        ("oven", "hvac"),
    ),
    TechnicianSeed(
        "Diego Ruiz",
        "312-555-0104",
        "diego.ruiz@searshs.example",
        "contractor",
        date(2023, 1, 9),
        ("60601", "60614", "60642"),
        ("washer", "hvac"),
    ),
    TechnicianSeed(
        "Jordan Lee",
        "214-555-0105",
        "jordan.lee@searshs.example",
        "full_time",
        date(2021, 8, 22),
        ("75201", "75204"),
        ("washer", "dryer"),
    ),
    TechnicianSeed(
        "Sofia Alvarez",
        "214-555-0106",
        "sofia.alvarez@searshs.example",
        "contractor",
        date(2022, 2, 14),
        ("75201", "75225"),
        ("refrigerator", "dishwasher"),
    ),
    TechnicianSeed(
        "Tom Becker",
        "214-555-0107",
        "tom.becker@searshs.example",
        "full_time",
        date(2019, 5, 30),
        ("75204", "75225"),
        ("oven", "hvac"),
    ),
    TechnicianSeed(
        "Nina Osei",
        "214-555-0108",
        "nina.osei@searshs.example",
        "contractor",
        date(2023, 9, 4),
        ("75201", "75204", "75225"),
        ("dryer", "dishwasher"),
    ),
)


async def _seed_specialties(session: AsyncSession) -> dict[str, str]:
    for name in APPLIANCE_TYPES:
        stmt = (
            pg_insert(Specialty)
            .values(name=name)
            .on_conflict_do_nothing(index_elements=[Specialty.name])
        )
        await session.execute(stmt)
    rows = (await session.execute(select(Specialty.id, Specialty.name))).all()
    return {name: str(sid) for sid, name in rows}


async def _seed_technicians(session: AsyncSession) -> dict[str, str]:
    for tech in TECHNICIANS:
        stmt = (
            pg_insert(Technician)
            .values(
                name=tech.name,
                phone=tech.phone,
                email=tech.email,
                employment_type=tech.employment_type,
                hired_on=tech.hired_on,
                active=True,
            )
            .on_conflict_do_nothing(index_elements=[Technician.email])
        )
        await session.execute(stmt)
    rows = (await session.execute(select(Technician.id, Technician.email))).all()
    return {email: str(tid) for tid, email in rows}


async def _seed_technician_specialties(
    session: AsyncSession, tech_ids: dict[str, str], specialty_ids: dict[str, str]
) -> None:
    for tech in TECHNICIANS:
        technician_id = tech_ids[tech.email]
        for specialty_name in tech.specialties:
            specialty_id = specialty_ids[specialty_name]
            stmt = (
                pg_insert(TechnicianSpecialty)
                .values(technician_id=technician_id, specialty_id=specialty_id)
                .on_conflict_do_nothing(
                    index_elements=[
                        TechnicianSpecialty.technician_id,
                        TechnicianSpecialty.specialty_id,
                    ]
                )
            )
            await session.execute(stmt)


async def _seed_service_areas(session: AsyncSession, tech_ids: dict[str, str]) -> None:
    for tech in TECHNICIANS:
        technician_id = tech_ids[tech.email]
        for zip_code in tech.zips:
            stmt = (
                pg_insert(ServiceArea)
                .values(technician_id=technician_id, zip_code=zip_code)
                .on_conflict_do_nothing(
                    index_elements=[ServiceArea.technician_id, ServiceArea.zip_code]
                )
            )
            await session.execute(stmt)


async def _seed_slots(session: AsyncSession, tech_ids: dict[str, str]) -> None:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for tech in TECHNICIANS:
        technician_id = tech_ids[tech.email]
        for day_offset in range(1, SLOT_HORIZON_DAYS + 1):
            day = today + timedelta(days=day_offset)
            for hour in SLOT_HOURS_UTC:
                starts_at = day.replace(hour=hour)
                ends_at = starts_at + timedelta(hours=SLOT_DURATION_HOURS)
                stmt = (
                    pg_insert(AvailabilitySlot)
                    .values(
                        technician_id=technician_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        status="open",
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            AvailabilitySlot.technician_id,
                            AvailabilitySlot.starts_at,
                        ]
                    )
                )
                await session.execute(stmt)


async def seed() -> None:
    """Idempotent: safe to run any number of times."""
    async with session_scope() as session:
        specialty_ids = await _seed_specialties(session)
        tech_ids = await _seed_technicians(session)
        await _seed_technician_specialties(session, tech_ids, specialty_ids)
        await _seed_service_areas(session, tech_ids)
        await _seed_slots(session, tech_ids)
        await session.commit()


async def _amain() -> None:
    await seed()
    engine = get_engine()
    await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()


__all__ = ["Base", "seed", "main", "TECHNICIANS"]
