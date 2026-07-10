"""Booking-bench self-cleanup contract (bugfix-loop T5) — DB half.

`scripts/booking_quality_bench.py` mutates the shared dev database (bench
customers, appointments, claimed slots, session rows) and promises to leave it
as found via its `finally` cleanup. That block had zero coverage — a broken
cleanup silently corrupts the shared DB across loop runs. Runs in the
scheduling lane so the autouse `_fresh_schema` fixture provisions the isolated
`<db>_test_scheduling` database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.db.matching import session_scope
from scripts.booking_quality_bench import BENCH_EMAIL_DOMAIN, cleanup_bench_rows

from .factories import make_slot, make_technician


async def _seed_bench_world() -> dict[str, uuid.UUID]:
    """A bench-marked booking (customer/appointment/booked slot/session) plus a
    civilian booking that must survive cleanup untouched."""
    ids: dict[str, uuid.UUID] = {}
    async with session_scope() as db:
        tech_id = await make_technician(db, zips=("60601",), specialties=("washer",))
        start = datetime.now(UTC) + timedelta(days=1)
        ids["bench_slot"] = await make_slot(db, technician_id=tech_id, starts_at=start)
        ids["civilian_slot"] = await make_slot(
            db, technician_id=tech_id, starts_at=start + timedelta(hours=2)
        )
        for key, email in (
            ("bench", f"caller{BENCH_EMAIL_DOMAIN}"),
            ("civilian", "real.person@example.com"),
        ):
            customer_id = uuid.uuid4()
            session_id = uuid.uuid4()
            slot_id = ids[f"{key}_slot"]
            await db.execute(
                sa.text(
                    "INSERT INTO customers (id, name, email, created_at)"
                    " VALUES (:id, :name, :email, now())"
                ),
                {"id": str(customer_id), "name": key, "email": email},
            )
            await db.execute(
                sa.text("INSERT INTO sessions (id, customer_id) VALUES (:id, :cid)"),
                {"id": str(session_id), "cid": str(customer_id)},
            )
            await db.execute(
                sa.text("UPDATE availability_slots SET status='booked' WHERE id = :sid"),
                {"sid": str(slot_id)},
            )
            await db.execute(
                sa.text(
                    "INSERT INTO appointments (id, slot_id, technician_id, customer_id,"
                    " session_id, appliance_type, issue_summary, status, created_at)"
                    " VALUES (:id, :slot, :tech, :cust, :sess, 'washer', 'won''t spin',"
                    " 'confirmed', now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "slot": str(slot_id),
                    "tech": str(tech_id),
                    "cust": str(customer_id),
                    "sess": str(session_id),
                },
            )
            ids[f"{key}_customer"] = customer_id
            ids[f"{key}_session"] = session_id
        await db.commit()
    return ids


async def _counts(ids: dict[str, uuid.UUID]) -> dict[str, object]:
    async with session_scope() as db:
        bench_customers = (
            await db.execute(
                sa.text("SELECT count(*) FROM customers WHERE email LIKE :pat"),
                {"pat": f"%{BENCH_EMAIL_DOMAIN}"},
            )
        ).scalar()
        civilian_appts = (
            await db.execute(
                sa.text("SELECT count(*) FROM appointments WHERE customer_id = :cid"),
                {"cid": str(ids["civilian_customer"])},
            )
        ).scalar()
        bench_slot_status = (
            await db.execute(
                sa.text("SELECT status FROM availability_slots WHERE id = :sid"),
                {"sid": str(ids["bench_slot"])},
            )
        ).scalar()
        civilian_slot_status = (
            await db.execute(
                sa.text("SELECT status FROM availability_slots WHERE id = :sid"),
                {"sid": str(ids["civilian_slot"])},
            )
        ).scalar()
        bench_sessions = (
            await db.execute(
                sa.text("SELECT count(*) FROM sessions WHERE id = :sid"),
                {"sid": str(ids["bench_session"])},
            )
        ).scalar()
    return {
        "bench_customers": bench_customers,
        "civilian_appts": civilian_appts,
        "bench_slot_status": bench_slot_status,
        "civilian_slot_status": civilian_slot_status,
        "bench_sessions": bench_sessions,
    }


async def test_cleanup_removes_bench_rows_and_reopens_slots_only_for_bench() -> None:
    ids = await _seed_bench_world()
    await cleanup_bench_rows(session_ids=[ids["bench_session"]], results=[], wiretap=None)
    state = await _counts(ids)
    assert state["bench_customers"] == 0
    assert state["bench_sessions"] == 0
    assert state["bench_slot_status"] == "open", "bench-claimed slot must be reopened"
    # The civilian booking is untouched.
    assert state["civilian_appts"] == 1
    assert state["civilian_slot_status"] == "booked"


async def test_cleanup_reopens_out_of_band_claimed_slot_from_results() -> None:
    ids = await _seed_bench_world()
    async with session_scope() as db:
        oob_slot = await make_slot(
            db,
            technician_id=await make_technician(db, name="OOB Tech", zips=("60602",)),
            starts_at=datetime.now(UTC) + timedelta(days=2),
        )
        await db.execute(
            sa.text("UPDATE availability_slots SET status='booked' WHERE id = :sid"),
            {"sid": str(oob_slot)},
        )
        await db.commit()
    await cleanup_bench_rows(
        session_ids=[ids["bench_session"]],
        results=[{"conflict_claimed_slot": str(oob_slot)}],
        wiretap=None,
    )
    async with session_scope() as db:
        status = (
            await db.execute(
                sa.text("SELECT status FROM availability_slots WHERE id = :sid"),
                {"sid": str(oob_slot)},
            )
        ).scalar()
    assert status == "open", "out-of-band claimed slot (no appointment row) must be reopened"
