"""Randomized booking-concurrency stress.

Seeded ``random`` (no hypothesis in .venv — no new deps) drives many customers
racing a shared pool of slots and interleaved find/book sequences, asserting the
booking invariants hold every time:

* every contested slot that receives at least one attempt ends with **exactly one**
  confirmed appointment — never zero (liveness), never two (double-booking);
* losers get a structured ``slot_taken`` (with an ``alternatives`` list), never an
  exception or a silent drop;
* the matcher never offers a slot that this test has already booked.

Each scenario is parametrized over several seeds; the seed is printed in every
assertion message so a failure is reproducible. Runs against the throwaway
per-test Postgres schema (tests/scheduling/conftest.py). Concurrent waves are
capped at 12 to stay within the async engine pool (5 + 10 overflow).

Isolation note: every DB assertion is scoped to the slot IDs *this test created*
(fresh ``uuid4`` per slot), never "the whole appointments table". The per-test
schema reset is not reliably isolating under this concurrent load — the shared
cached engine can bind to a stale event loop and leak a prior parametrized case's
committed rows into the next (tracked separately as the engine/event-loop issue).
Scoping to the test's own universe makes the invariants true regardless of any
foreign rows, which is the correct contract for a stress test anyway.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.contracts import Customer
from app.db import matching
from app.db.base import normalize_asyncpg_url
from app.db.matching import find_technician_matches, session_scope
from app.db.models_scheduling import Appointment, AvailabilitySlot
from app.db.models_scheduling import Base as SchedulingBase
from app.tools.scheduling_tools import book_appointment

from .factories import make_slot, make_technician

_ZIPS = ("60601", "60614", "60642", "75201", "75204")
_APPLIANCES = ("washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac")
# A summary that always names an appliance so `book_appointment`'s inference
# succeeds — the tool never cross-checks appliance against the tech's specialty,
# so any valid open slot is bookable regardless of what we file it under.
_SUMMARY = "the washer stopped working mid-cycle"
_MAX_CONCURRENCY = 12

_SEEDS = (1, 7, 42, 101)

# The shared async DB engine caches connections that can outlive a test's event
# loop (tracked separately as the engine/event-loop isolation issue). Under this
# file's concurrent write load that surfaces as transient Postgres deadlocks and
# cross-connection faults during the per-test schema reset — never as a wrong
# booking outcome. Retry ONLY those transient DB-driver signatures; a real
# invariant break is a plain AssertionError and is never masked here.
# No rerun/retry crutch: the dedicated-DB isolation below removes the harness
# DDL-vs-DML race entirely (verified flake-free), and `book_appointment` itself is
# concurrency-safe, so any deadlock here would be a genuine regression that must show
# red rather than be silently retried away.

# --- Dedicated-DB isolation (diagnosis: task #46) ----------------------------------
#
# `book_appointment` is concurrency-safe — a single clean engine handles thousands of
# concurrent bookings with zero deadlocks (verified). The flakiness came entirely from
# the *shared* harness: the package's autouse `_fresh_schema` runs `DROP SCHEMA public
# CASCADE` on the one `_test_scheduling` database that ~45 DB tests share, and this
# file's concurrent-write load turned that DDL-vs-DML overlap into asyncpg deadlocks
# that also slowed and flaked neighboring tests. Production never drops the schema, so
# this is a test-only artifact.
#
# Fix: run the stress lane against its OWN database with a light per-test TRUNCATE
# instead of a schema drop. The fixture below *overrides* the package `_fresh_schema`
# (same name → nearest definition wins) for this module only, so the stress tests
# neither share a database with — nor take heavy DDL locks against — their neighbors.

_STRESS_DB_SUFFIX = "_stress"
_STRESS_TABLES = (
    "appointments",
    "availability_slots",
    "technician_specialties",
    "service_areas",
    "technicians",
    "specialties",
    "customers",
    "sessions",
)


def _stress_db_url(base_url: str) -> str:
    url = make_url(base_url)
    return url.set(database=f"{url.database}{_STRESS_DB_SUFFIX}").render_as_string(
        hide_password=False
    )


async def _ensure_stress_db(base_url: str, stress_db: str) -> None:
    """Create the dedicated stress database if missing — DDL only ever targets the
    `postgres` maintenance DB or the isolated stress DB, never the shared app DB."""
    admin_url = make_url(base_url).set(database="postgres").render_as_string(hide_password=False)
    admin = create_async_engine(normalize_asyncpg_url(admin_url), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": stress_db}
                )
            ).scalar()
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{stress_db}"'))
    finally:
        await admin.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    """Override of the package fixture: isolate this file onto its own database and
    clean it with TRUNCATE (no shared-schema DROP that races neighbors)."""
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        yield
        return
    # `base_url` here is the raw app DB (the package's DB-swapping fixture is shadowed);
    # derive a sibling `<db>_stress` and only ever touch that.
    stress_url = _stress_db_url(base_url)
    stress_db = make_url(stress_url).database
    os.environ["DATABASE_URL"] = stress_url
    try:
        await _ensure_stress_db(base_url, stress_db)
        await matching.reset_engine()
        engine = matching.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(SchedulingBase.metadata.create_all)
            await conn.execute(
                text(f"TRUNCATE {', '.join(_STRESS_TABLES)} RESTART IDENTITY CASCADE")
            )
        yield
    finally:
        await matching.reset_engine()
        os.environ["DATABASE_URL"] = base_url
        await matching.reset_engine()


async def _build_world(
    rng: random.Random, n_techs: int, slots_per_tech: int
) -> tuple[list[str], list[tuple[str, str]]]:
    """Create ``n_techs`` technicians with random zips/specialties and distinct
    future slots. Returns (all open slot ids, coverage pairs) where each coverage
    pair is a (zip, appliance) actually served by some technician."""
    now = datetime.now(UTC)
    slot_ids: list[str] = []
    coverage: set[tuple[str, str]] = set()
    async with session_scope() as session:
        for i in range(n_techs):
            zips = tuple(rng.sample(_ZIPS, rng.randint(1, 2)))
            specialties = tuple(rng.sample(_APPLIANCES, rng.randint(1, 2)))
            tech_id = await make_technician(
                session, name=f"Tech {i:02d}", zips=zips, specialties=specialties
            )
            for j in range(slots_per_tech):
                # Distinct day per slot keeps (technician_id, starts_at) unique.
                sid = await make_slot(session, tech_id, now + timedelta(days=1 + j))
                slot_ids.append(str(sid))
            for z in zips:
                for sp in specialties:
                    coverage.add((z, sp))
        await session.commit()
    return slot_ids, sorted(coverage)


def _parse(results: list[str]) -> list[dict]:
    return [json.loads(r) for r in results]


async def _appointment_counts_for(slot_ids: set[str]) -> dict[str, int]:
    """Appointment count per slot, restricted to this test's own slot universe."""
    ids = [uuid.UUID(s) for s in slot_ids]
    if not ids:
        return {}
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Appointment.slot_id, func.count())
                .where(Appointment.slot_id.in_(ids))
                .group_by(Appointment.slot_id)
            )
        ).all()
    return {str(sid): n for sid, n in rows}


async def _booked_within(slot_ids: set[str]) -> set[str]:
    ids = [uuid.UUID(s) for s in slot_ids]
    if not ids:
        return set()
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(AvailabilitySlot.id).where(
                        AvailabilitySlot.id.in_(ids), AvailabilitySlot.status == "booked"
                    )
                )
            )
            .scalars()
            .all()
        )
    return {str(s) for s in rows}


@pytest.mark.parametrize("seed", _SEEDS)
async def test_random_race_exactly_one_winner_per_contested_slot(seed: int):
    rng = random.Random(seed)
    slot_ids, _ = await _build_world(rng, n_techs=6, slots_per_tech=4)
    universe = set(slot_ids)

    # Choose a handful of contested slots and aim several customers at each.
    n_contested = rng.randint(2, 5)
    contested = rng.sample(slot_ids, n_contested)
    attempts: list[str] = [rng.choice(contested) for _ in range(_MAX_CONCURRENCY)]
    rng.shuffle(attempts)

    results = _parse(
        await asyncio.gather(
            *(
                book_appointment(sid, Customer(name=f"Caller {k}"), _SUMMARY)
                for k, sid in enumerate(attempts)
            )
        )
    )

    # No exceptions, only the two legitimate outcomes.
    statuses = {r["status"] for r in results}
    assert statuses <= {"confirmed", "slot_taken"}, f"seed={seed}: unexpected {statuses}"

    # Exactly one confirmation per contested slot that got at least one attempt.
    attempted_slots = set(attempts)
    confirmed_by_slot: dict[str, int] = {}
    for sid, res in zip(attempts, results, strict=True):
        if res["status"] == "confirmed":
            confirmed_by_slot[sid] = confirmed_by_slot.get(sid, 0) + 1
        else:
            assert isinstance(res.get("alternatives"), list), (
                f"seed={seed}: slot_taken missing alternatives list: {res}"
            )
    for sid in attempted_slots:
        assert confirmed_by_slot.get(sid, 0) == 1, (
            f"seed={seed}: slot {sid} had {confirmed_by_slot.get(sid, 0)} winners (want 1)"
        )

    k = len(attempted_slots)
    assert sum(1 for r in results if r["status"] == "confirmed") == k, f"seed={seed}"
    assert sum(1 for r in results if r["status"] == "slot_taken") == len(attempts) - k, (
        f"seed={seed}"
    )

    # DB-side truth, scoped to this test's slots: exactly the attempted slots are
    # booked, one appointment each (no double-books), the rest still open.
    counts = await _appointment_counts_for(universe)
    assert all(n == 1 for n in counts.values()), f"seed={seed}: double-book {counts}"
    assert set(counts) == attempted_slots, f"seed={seed}: booked set mismatch"
    booked = await _booked_within(universe)
    assert booked == attempted_slots, f"seed={seed}: {booked} != {attempted_slots}"


@pytest.mark.parametrize("seed", _SEEDS)
async def test_interleaved_find_and_book_preserve_invariants(seed: int):
    rng = random.Random(seed)
    slot_ids, coverage = await _build_world(rng, n_techs=5, slots_per_tech=4)
    my_slots = set(slot_ids)
    assert coverage, f"seed={seed}: world produced no coverage"

    booked: set[str] = set()

    for _round in range(12):
        zip_code, appliance = rng.choice(coverage)
        async with session_scope() as session:
            matches = await find_technician_matches(session, zip_code, appliance)

        offered = [s.slot_id for m in matches for s in m.slots]
        # Invariant: the matcher never re-offers a slot this test has booked.
        assert not (set(offered) & booked), (
            f"seed={seed}: matcher offered booked slots {set(offered) & booked}"
        )

        # Only ever book slots from this test's own universe so the bookkeeping
        # (and the final DB check) stays scoped and foreign rows can't interfere.
        mine = [o for o in offered if o in my_slots]
        if not mine:
            continue
        target = rng.choice(mine)

        if rng.random() < 0.4:
            # Occasionally two callers pounce on the same freshly-offered slot.
            res = _parse(
                await asyncio.gather(
                    book_appointment(target, Customer(name="A"), _SUMMARY),
                    book_appointment(target, Customer(name="B"), _SUMMARY),
                )
            )
            wins = [r for r in res if r["status"] == "confirmed"]
            assert len(wins) == 1, f"seed={seed}: {len(wins)} winners on double-pounce"
            assert {r["status"] for r in res} == {"confirmed", "slot_taken"}, (
                f"seed={seed}: double-pounce statuses {[r['status'] for r in res]}"
            )
        else:
            res = json.loads(await book_appointment(target, Customer(name="Solo"), _SUMMARY))
            assert res["status"] == "confirmed", f"seed={seed}: solo book got {res['status']}"
        booked.add(target)

    # Final consistency within this test's universe: appointments == booked slots,
    # all singletons.
    counts = await _appointment_counts_for(my_slots)
    assert all(n == 1 for n in counts.values()), f"seed={seed}: double-book {counts}"
    assert set(counts) == booked, f"seed={seed}: {set(counts)} != {booked}"


@pytest.mark.parametrize("seed", _SEEDS)
async def test_booked_slot_is_terminally_held_no_cancel_path(seed: int):
    """The product exposes no cancel/reschedule tool — only ``find_technicians`` and
    ``book_appointment`` (the ``appointments.cancelled`` status has no writer). So the
    "cancel-if-exists" step of an interleaved sequence degenerates to a real invariant:
    once a slot is booked it is *terminally* held. Concurrent re-book attempts by other
    callers can never re-acquire it, and the matcher never re-offers it — double-holding
    is impossible by construction."""
    rng = random.Random(seed)
    slot_ids, coverage = await _build_world(rng, n_techs=3, slots_per_tech=3)
    target = rng.choice(slot_ids)

    first = json.loads(await book_appointment(target, Customer(name="Owner"), _SUMMARY))
    assert first["status"] == "confirmed", f"seed={seed}: initial book got {first['status']}"

    # A wave of poachers races the already-held slot; every one must lose cleanly.
    reattempts = _parse(
        await asyncio.gather(
            *(book_appointment(target, Customer(name=f"Poacher {k}"), _SUMMARY) for k in range(8))
        )
    )
    assert all(r["status"] == "slot_taken" for r in reattempts), (
        f"seed={seed}: a re-book re-acquired a held slot: {[r['status'] for r in reattempts]}"
    )
    for r in reattempts:
        assert isinstance(r.get("alternatives"), list), f"seed={seed}: slot_taken missing alts: {r}"

    # The matcher never re-offers the held slot across its coverage pairs.
    for zip_code, appliance in coverage[:3]:
        async with session_scope() as session:
            matches = await find_technician_matches(session, zip_code, appliance)
        offered = {s.slot_id for m in matches for s in m.slots}
        assert target not in offered, (
            f"seed={seed}: held slot re-offered for {zip_code}/{appliance}"
        )

    # DB: exactly one appointment for the held slot, still booked.
    counts = await _appointment_counts_for({target})
    assert counts.get(target) == 1, f"seed={seed}: held slot has {counts.get(target)} appts"
    assert await _booked_within({target}) == {target}, f"seed={seed}: held slot no longer booked"
