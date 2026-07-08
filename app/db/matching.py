"""Zip + specialty matching, and the shared async DB session factory.

Owned by the technician-scheduling feature. No shared ``app/db`` session helper
exists yet in the foundation scaffold (COORDINATION.md §3 assigns no such file to
any feature), so this module owns a small lazily-built async engine/sessionmaker
built from ``DATABASE_URL`` (the pooled connection string used by app code;
migrations use ``DATABASE_URL_DIRECT`` via ``alembic/env.py`` — a separate,
unrelated connection). ``app/db/seed.py`` and ``app/tools/scheduling_tools.py``
(both owned by this feature) import ``session_scope`` from here.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.contracts import Appliance
from app.db.base import normalize_asyncpg_url
from app.db.models_scheduling import (
    AvailabilitySlot,
    ServiceArea,
    Specialty,
    Technician,
    TechnicianSpecialty,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL must be set.")
        # Shared normalizer (app/db/base.py): forces the asyncpg driver AND translates
        # libpq TLS params (sslmode -> ssl, drop channel_binding) that asyncpg rejects.
        # A Neon pooled DATABASE_URL carries ?sslmode=require&channel_binding=require,
        # so the string-only scheme swap this used to do raised
        # "connect() got an unexpected keyword argument 'sslmode'" against real Neon.
        _engine = create_async_engine(normalize_asyncpg_url(url), pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """One session per call — callers ``commit()``/``rollback()`` explicitly."""
    maker = get_sessionmaker()
    async with maker() as session:
        yield session


async def reset_engine() -> None:
    """Test hook: dispose the cached engine so a new event loop / DATABASE_URL
    takes effect (asyncpg connections are bound to the loop that created them,
    which changes between pytest-asyncio tests)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


# --- Matching ----------------------------------------------------------------


@dataclass
class SlotOption:
    slot_id: str
    starts_at: datetime
    ends_at: datetime


@dataclass
class TechnicianMatch:
    technician_id: str
    name: str
    slots: list[SlotOption] = field(default_factory=list)


_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_DAY_PARTS = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
}


def parse_window(
    window: str | None, now: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """Best-effort parse of a free-text availability hint into [start, end).

    Recognizes a weekday name ("tuesday") and/or a day part ("morning" /
    "afternoon" / "evening"), e.g. "Tuesday afternoon", "tomorrow morning",
    "next week". Unparseable or ``None`` input returns ``(None, None)`` — no
    filtering (Decision: soft preference, not a hard filter — see
    ``find_technician_matches``, which falls back to unfiltered results if a
    window filter yields nothing).
    """
    if not window:
        return None, None
    now = now or datetime.now(UTC)
    text = window.strip().lower()

    target_date: datetime | None = None
    if "tomorrow" in text:
        target_date = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        for i, day_name in enumerate(_WEEKDAYS):
            if re.search(rf"\b{day_name}\b", text):
                days_ahead = (i - now.weekday()) % 7
                days_ahead = days_ahead or 7  # "tuesday" said on a Tuesday means next Tuesday
                target_date = (now + timedelta(days=days_ahead)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                break

    day_part = None
    for part, _hours in _DAY_PARTS.items():
        if part in text:
            day_part = part
            break

    if target_date is None and day_part is None:
        return None, None

    base_date = target_date or now.replace(hour=0, minute=0, second=0, microsecond=0)
    if day_part is not None:
        start_hour, end_hour = _DAY_PARTS[day_part]
        start = base_date.replace(hour=start_hour)
        end = base_date.replace(hour=end_hour)
    else:
        # A bare weekday/"tomorrow" with no day part: the whole day.
        start = base_date
        end = base_date + timedelta(days=1)

    return start, end


async def find_technician_matches(
    session: AsyncSession,
    zip_code: str,
    appliance_type: Appliance,
    window: str | None = None,
    now: datetime | None = None,
    max_slots_per_technician: int = 3,
) -> list[TechnicianMatch]:
    """Zip + specialty join over open future slots, soonest first.

    Returns technicians (service area = ``zip_code``, specialty =
    ``appliance_type``, active) each carrying up to
    ``max_slots_per_technician`` open future slots ordered by ``starts_at``
    ascending. ``window`` is a soft preference (Decision, requirements.md open
    question resolved): if it narrows the result to zero technicians, the
    unfiltered soonest-first result is returned instead of an empty list.
    """
    now = now or datetime.now(UTC)

    async def _query(window_start: datetime | None, window_end: datetime | None):
        stmt = (
            select(
                Technician.id,
                Technician.name,
                AvailabilitySlot.id,
                AvailabilitySlot.starts_at,
                AvailabilitySlot.ends_at,
            )
            .join(ServiceArea, ServiceArea.technician_id == Technician.id)
            .join(TechnicianSpecialty, TechnicianSpecialty.technician_id == Technician.id)
            .join(Specialty, Specialty.id == TechnicianSpecialty.specialty_id)
            .join(AvailabilitySlot, AvailabilitySlot.technician_id == Technician.id)
            .where(
                Technician.active.is_(True),
                ServiceArea.zip_code == zip_code,
                Specialty.name == appliance_type,
                AvailabilitySlot.status == "open",
                AvailabilitySlot.starts_at > now,
            )
            .order_by(Technician.name, AvailabilitySlot.starts_at)
        )
        if window_start is not None:
            stmt = stmt.where(AvailabilitySlot.starts_at >= window_start)
        if window_end is not None:
            stmt = stmt.where(AvailabilitySlot.starts_at < window_end)
        result = await session.execute(stmt)
        return result.all()

    window_start, window_end = parse_window(window, now=now)
    rows = await _query(window_start, window_end)
    if not rows and (window_start is not None or window_end is not None):
        # Soft preference: fall back to the unfiltered soonest-first result.
        rows = await _query(None, None)

    matches: dict[str, TechnicianMatch] = {}
    order: list[str] = []
    for tech_id, tech_name, slot_id, starts_at, ends_at in rows:
        key = str(tech_id)
        if key not in matches:
            matches[key] = TechnicianMatch(technician_id=key, name=tech_name)
            order.append(key)
        match = matches[key]
        if len(match.slots) < max_slots_per_technician:
            match.slots.append(
                SlotOption(slot_id=str(slot_id), starts_at=starts_at, ends_at=ends_at)
            )

    return [matches[k] for k in order]


async def find_alternative_slots(
    session: AsyncSession,
    technician_id: str,
    now: datetime | None = None,
    limit: int = 3,
) -> list[SlotOption]:
    """Next open future slots for one technician (used for the ``slot_taken`` reply)."""
    now = now or datetime.now(UTC)
    stmt = (
        select(AvailabilitySlot.id, AvailabilitySlot.starts_at, AvailabilitySlot.ends_at)
        .where(
            AvailabilitySlot.technician_id == technician_id,
            AvailabilitySlot.status == "open",
            AvailabilitySlot.starts_at > now,
        )
        .order_by(AvailabilitySlot.starts_at)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        SlotOption(slot_id=str(sid), starts_at=starts_at, ends_at=ends_at)
        for sid, starts_at, ends_at in rows
    ]
