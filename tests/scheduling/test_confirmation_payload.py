"""Booking confirmation payload carries the claimed slot's times (T9, DB half).

The confirmed payload's `starts_at`/`ends_at` are what the agent verbally
reads back to the caller (Tier-2 "verbal confirmation" requirement) — yet no
test ever asserted them. Runs in the scheduling lane (isolated test DB via the
autouse conftest fixture).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.contracts import Customer
from app.db.matching import session_scope
from app.tools.scheduling_tools import book_appointment

from .factories import make_slot, make_technician


async def test_confirmed_payload_reads_back_the_exact_slot_times() -> None:
    starts_at = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    ends_at = starts_at + timedelta(hours=2)
    async with session_scope() as db:
        tech_id = await make_technician(db, name="Alex Chen", zips=("60601",))
        slot_id = await make_slot(db, technician_id=tech_id, starts_at=starts_at, ends_at=ends_at)
        await db.commit()

    payload = json.loads(
        await book_appointment(
            str(slot_id),
            Customer(name="Jamie Rivera", zip="60601", email="jamie@example.com"),
            "washer bangs during spin",
        )
    )
    assert payload["status"] == "confirmed"
    assert payload["technician"] == "Alex Chen"
    # The verbal read-back data must be the claimed slot's exact instants.
    assert datetime.fromisoformat(payload["starts_at"]) == starts_at
    assert datetime.fromisoformat(payload["ends_at"]) == ends_at
    assert payload["appointment_id"]
