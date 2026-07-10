"""Hermetic appointment-requirements bench — the appointment-requirements loop's metric
(appointment-requirements-iterate q1).

Six keyless probes encode the take-home spec's Tier 2 "Technician Scheduling"
requirements (plus Tier 1's never-re-ask) as machine-checkable facts, so spec
conformance is measured continuously instead of re-read from the PDF:

- ``r_db_schema`` — the scheduling schema the assignment asks for exists with its
                    integrity guards (6 tables, slot uniqueness, appointment FKs),
                    introspected on a throwaway in-memory SQLite database.
- ``r_seed``      — seed adequacy from the static ``app.db.seed`` constants: >= 5
                    technicians, multiple zips across >= 2 metro clusters, all six
                    appliance specialties covered. No database touched.
- ``r_match``     — the REAL ``find_technician_matches`` on in-memory SQLite
                    (aiosqlite) over a dataset derived from the seed constants with a
                    fixed clock: zip∧specialty join, soonest-first, <= 3 slots/tech,
                    unknown zip empty, soft-window fallback, booked/past excluded.
- ``r_flow``      — the scheduling-flow contract text + offered-slot rendering +
                    scenario coverage. Sub-checks ``zip_validation`` (f1) and
                    ``phone_offered_slots`` (f3) start ``enforced: false``.
- ``r_confirm``   — the verbal read-back contract. Sub-check ``readback_fixture``
                    (q2 flips ``enforced``) runs the deterministic read-back
                    assertion against the committed positive fixture AND the
                    no-read-back canary (the canary IS the mutation detector).
                    Sub-check ``explicit_appliance_param`` (f2) starts advisory.
- ``r_memory``    — never-re-ask: prompt rules + ``check_structural_assertions``
                    passing the committed fixture and FAILING a synthetic violating
                    one (detector proven live inside the metric).

An ``advisory.db_live`` section (real Postgres row counts + one live matching smoke)
runs only when ``DATABASE_URL`` is reachable and NEVER affects ``overall_pass`` —
the hard-gate lanes stay hermetic.

Writes ``data/appt_req/<utc-ts>.json`` (schema in the loop protocol §10) and prints a
one-line verdict per probe. Soft gate until the loop's terminal gate-flip:
``APPT_REQ_GATE_HARD=1`` makes a failing report exit 1.
"""

from __future__ import annotations

import asyncio
import inspect as py_inspect
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

SCHEMA_VERSION = 1
OUT_DIR = Path(os.environ.get("APPT_REQ_BENCH_DIR", "data/appt_req"))
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures" / "transcripts"
SCENARIOS_DIR = REPO_ROOT / "evals" / "scenarios"

# Seed adequacy budgets (assignment: "at least 5-10 technicians across multiple zip
# codes and specialties"; repo requirements.md: 8 techs, ~6 zips, two metro clusters).
MIN_TECHNICIANS = 5
MIN_DISTINCT_ZIPS = 4
MIN_METRO_CLUSTERS = 2
MIN_SLOT_HORIZON_DAYS = 7

# The matching probe's fixed clock — nothing in it may read the wall clock, so the
# probe is bit-for-bit reproducible.
MATCH_NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)

# Flipped by the owning fix's commit (q2 / f1 / f2 / f3) — never to make a run pass.
READBACK_FIXTURE_ENFORCED = False
ZIP_VALIDATION_ENFORCED = False
EXPLICIT_APPLIANCE_PARAM_ENFORCED = False
PHONE_OFFERED_SLOTS_ENFORCED = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_fk_standins() -> None:
    """Register minimal ``customers``/``sessions`` stand-ins on the scheduling Base's
    MetaData (same shapes tests/scheduling/conftest.py uses) so ``appointments``'
    string-form FK targets resolve during create_all. Idempotent via extend_existing."""
    from app.db.models_scheduling import Base

    sa.Table(
        "customers",
        Base.metadata,
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120)),
        sa.Column("phone", sa.String(20)),
        sa.Column("email", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        extend_existing=True,
    )
    sa.Table(
        "sessions",
        Base.metadata,
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", PGUUID(as_uuid=True), sa.ForeignKey("customers.id")),
        extend_existing=True,
    )


def _load_fixture(name: str) -> dict[str, Any] | None:
    path = FIXTURES_DIR / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_scenario(rel_path: str):
    from evals.scenarios.schema import load_scenario_file

    path = SCENARIOS_DIR / rel_path
    if not path.exists():
        return None
    return load_scenario_file(path)


# --- probes -------------------------------------------------------------------------


def probe_r_db_schema(metadata: sa.MetaData | None = None) -> dict:
    """R-DB: the assignment's scheduling schema exists with its integrity guards,
    introspected on a throwaway in-memory SQLite database (no external DB)."""
    if metadata is None:
        _ensure_fk_standins()
        from app.db.models_scheduling import Base

        metadata = Base.metadata

    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    inspector = sa.inspect(engine)

    required_tables = {
        "technicians",
        "specialties",
        "technician_specialties",
        "service_areas",
        "availability_slots",
        "appointments",
    }
    tables = set(inspector.get_table_names())
    checks: dict[str, bool] = {"tables": required_tables <= tables}

    if "availability_slots" in tables:
        uniques = inspector.get_unique_constraints("availability_slots")
        columns = {c["name"] for c in inspector.get_columns("availability_slots")}
        checks["slot_unique"] = any(
            set(uc["column_names"]) == {"technician_id", "starts_at"} for uc in uniques
        )
        checks["slot_status_column"] = "status" in columns
    else:
        checks["slot_unique"] = checks["slot_status_column"] = False

    if "appointments" in tables:
        fk_targets = {
            (tuple(fk["constrained_columns"]), fk["referred_table"])
            for fk in inspector.get_foreign_keys("appointments")
        }
        checks["appointment_fks"] = {
            (("slot_id",), "availability_slots"),
            (("technician_id",), "technicians"),
            (("customer_id",), "customers"),
            (("session_id",), "sessions"),
        } <= fk_targets
        uniques = inspector.get_unique_constraints("appointments")
        unique_indexes = [ix for ix in inspector.get_indexes("appointments") if ix["unique"]]
        checks["slot_fk_unique"] = any(uc["column_names"] == ["slot_id"] for uc in uniques) or any(
            ix["column_names"] == ["slot_id"] for ix in unique_indexes
        )
    else:
        checks["appointment_fks"] = checks["slot_fk_unique"] = False

    if "service_areas" in tables:
        indexes = inspector.get_indexes("service_areas")
        checks["zip_index"] = any(ix["column_names"] == ["zip_code"] for ix in indexes)
    else:
        checks["zip_index"] = False

    return {"checks": checks, "budget": {"all_checks": True}, "pass": all(checks.values())}


def probe_r_seed(
    technicians: tuple | None = None,
    horizon_days: int | None = None,
    slot_hours: tuple | None = None,
) -> dict:
    """R-DB seeding adequacy from the static seed constants — no database."""
    from app.db import seed
    from app.db.models_scheduling import APPLIANCE_TYPES

    technicians = technicians if technicians is not None else seed.TECHNICIANS
    horizon_days = horizon_days if horizon_days is not None else seed.SLOT_HORIZON_DAYS
    slot_hours = slot_hours if slot_hours is not None else seed.SLOT_HOURS_UTC

    zips = {z for t in technicians for z in t.zips}
    clusters = {z[:3] for z in zips}
    specialties = {s for t in technicians for s in t.specialties}
    emails = [t.email for t in technicians]

    checks = {
        "min_technicians": len(technicians) >= MIN_TECHNICIANS,
        "min_zips": len(zips) >= MIN_DISTINCT_ZIPS,
        "min_clusters": len(clusters) >= MIN_METRO_CLUSTERS,
        "specialties_covered": specialties == set(APPLIANCE_TYPES),
        "every_tech_has_zip_and_specialty": all(t.zips and t.specialties for t in technicians),
        "emails_unique": len(emails) == len(set(emails)),
        "slot_horizon": horizon_days >= MIN_SLOT_HORIZON_DAYS and len(slot_hours) > 0,
    }
    return {
        "technicians": len(technicians),
        "distinct_zips": len(zips),
        "metro_clusters": len(clusters),
        "specialties_covered": len(specialties),
        "checks": checks,
        "budget": {
            "min_technicians": MIN_TECHNICIANS,
            "min_zips": MIN_DISTINCT_ZIPS,
            "min_clusters": MIN_METRO_CLUSTERS,
            "specialties_covered": len(APPLIANCE_TYPES),
        },
        "pass": all(checks.values()),
    }


async def _build_match_dataset(session) -> dict[str, Any]:
    """Deterministic dataset derived from the seed constants: every seed technician,
    zip, and specialty; 4 open slots/day for 3 days from MATCH_NOW; plus one booked
    and one past slot per technician (the exclusion detectors)."""
    from app.db import seed
    from app.db.models_scheduling import (
        APPLIANCE_TYPES,
        AvailabilitySlot,
        ServiceArea,
        Specialty,
        Technician,
        TechnicianSpecialty,
    )

    specialty_ids: dict[str, uuid.UUID] = {}
    for name in APPLIANCE_TYPES:
        sid = uuid.uuid4()
        specialty_ids[name] = sid
        session.add(Specialty(id=sid, name=name))

    tech_ids: dict[str, uuid.UUID] = {}
    booked_slot_ids: list[str] = []
    past_slot_ids: list[str] = []
    for tech in seed.TECHNICIANS:
        tid = uuid.uuid4()
        tech_ids[tech.email] = tid
        session.add(
            Technician(
                id=tid,
                name=tech.name,
                phone=tech.phone,
                email=tech.email,
                employment_type=tech.employment_type,
                hired_on=date(2021, 1, 1),
                active=True,
            )
        )
        for zip_code in tech.zips:
            session.add(ServiceArea(technician_id=tid, zip_code=zip_code))
        for specialty in tech.specialties:
            session.add(
                TechnicianSpecialty(technician_id=tid, specialty_id=specialty_ids[specialty])
            )
        day0 = MATCH_NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(1, 4):
            for hour in (9, 11, 13, 15):
                starts_at = day0 + timedelta(days=day_offset, hours=hour)
                session.add(
                    AvailabilitySlot(
                        id=uuid.uuid4(),
                        technician_id=tid,
                        starts_at=starts_at,
                        ends_at=starts_at + timedelta(hours=2),
                        status="open",
                    )
                )
        # Exclusion detectors: a booked slot SOONER than every open one, and a past slot.
        booked_id, past_id = uuid.uuid4(), uuid.uuid4()
        booked_at = day0 + timedelta(hours=20)  # today 20:00 — before tomorrow 09:00
        session.add(
            AvailabilitySlot(
                id=booked_id,
                technician_id=tid,
                starts_at=booked_at,
                ends_at=booked_at + timedelta(hours=2),
                status="booked",
            )
        )
        past_at = MATCH_NOW - timedelta(days=1)
        session.add(
            AvailabilitySlot(
                id=past_id,
                technician_id=tid,
                starts_at=past_at,
                ends_at=past_at + timedelta(hours=2),
                status="open",
            )
        )
        booked_slot_ids.append(str(booked_id))
        past_slot_ids.append(str(past_id))

    await session.flush()
    return {"booked": set(booked_slot_ids), "past": set(past_slot_ids)}


async def probe_r_match() -> dict:
    """R-MATCH: the production ``find_technician_matches`` query, exercised on
    in-memory SQLite with a fixed clock (aiosqlite; nothing external)."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.db import seed
    from app.db.matching import find_technician_matches
    from app.db.models_scheduling import Base

    _ensure_fk_standins()
    engine = create_async_engine("sqlite+aiosqlite://")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            excluded = await _build_match_dataset(session)

            matches = await find_technician_matches(session, "60614", "washer", now=MATCH_NOW)
            expected = {
                t.name for t in seed.TECHNICIANS if "60614" in t.zips and "washer" in t.specialties
            }
            checks["zip_specialty_join"] = {m.name for m in matches} == expected and bool(expected)
            checks["soonest_first"] = all(
                m.slots == sorted(m.slots, key=lambda s: s.starts_at) for m in matches
            )
            checks["max_three_slots"] = bool(matches) and all(len(m.slots) <= 3 for m in matches)
            returned_slot_ids = {s.slot_id for m in matches for s in m.slots}
            checks["excludes_booked_and_past"] = not (
                returned_slot_ids & (excluded["booked"] | excluded["past"])
            )

            checks["no_tech_zip_empty"] = (
                await find_technician_matches(session, "98101", "washer", now=MATCH_NOW) == []
            )

            # Soft window preference: slots sit at 09-15 UTC, so an "evening" window
            # matches nothing and must fall back to the unfiltered soonest-first list.
            windowed = await find_technician_matches(
                session, "60614", "washer", window="evening", now=MATCH_NOW
            )
            checks["window_soft_fallback"] = {m.name for m in windowed} == expected
    finally:
        await engine.dispose()

    return {"checks": checks, "budget": {"all_checks": True}, "pass": all(checks.values())}


def probe_r_flow(contract_text: str | None = None) -> dict:
    """R-FLOW: collect availability, propose <= 3 matching slots — pinned in the
    prompt contract, the offered-slot rendering, the matching default, and the
    scenario matrix."""
    from app.agent import prompts
    from app.db.matching import find_technician_matches

    contract = contract_text if contract_text is not None else prompts.SCHEDULING_CONTRACT

    rendered = prompts._render_offered_slots(
        [{"ref": "slot_1", "technician": "Ava Chen", "starts_at": "9", "ends_at": "11"}]
    )
    scheduling_scenarios = [
        "scheduling/happy_booking.yaml",
        "scheduling/no_tech_in_zip.yaml",
        "scheduling/slot_conflict.yaml",
        "scheduling/zip_never_reasked.yaml",
    ]
    loaded = [_load_scenario(rel) for rel in scheduling_scenarios]

    checks = {
        "contract_max_three": "at most 3 options" in contract,
        "contract_zip_first": "Zip is required before `find_technicians`" in contract,
        "contract_availability_window": "availability window" in contract,
        "contract_slot_id_verbatim": "verbatim" in contract,
        "offered_slots_rendering": "ALREADY offered" in rendered and "slot_1" in rendered,
        "match_default_limit_3": (
            py_inspect.signature(find_technician_matches)
            .parameters["max_slots_per_technician"]
            .default
            == 3
        ),
        "scenario_coverage": all(s is not None and s.feature == "scheduling" for s in loaded),
    }

    zip_validation = _subcheck_zip_validation()
    phone_offered_slots = _subcheck_phone_offered_slots()

    enforced_ok = all(
        sub["pass"] for sub in (zip_validation, phone_offered_slots) if sub["enforced"]
    )
    return {
        "checks": checks,
        "zip_validation": zip_validation,
        "phone_offered_slots": phone_offered_slots,
        "budget": {"all_enforced_checks": True},
        "pass": all(checks.values()) and enforced_ok,
    }


def _subcheck_zip_validation() -> dict:
    """f1: `_normalize_zip` in scheduling_tools — 5-digit US zips (ZIP+4 collapses),
    garbage rejected. Advisory until f1 lands and flips ZIP_VALIDATION_ENFORCED."""
    from app.tools import scheduling_tools

    normalize = getattr(scheduling_tools, "_normalize_zip", None)
    if normalize is None:
        return {"enforced": ZIP_VALIDATION_ENFORCED, "available": False, "pass": False}
    behavior_ok = (
        normalize("60614") == "60614"
        and normalize(" 60614 ") == "60614"
        and normalize("60614-1234") == "60614"
        and normalize("abcde") is None
        and normalize("6061") is None
    )
    return {"enforced": ZIP_VALIDATION_ENFORCED, "available": True, "pass": behavior_ok}


def _subcheck_phone_offered_slots() -> dict:
    """f3: the phone channel's prompt refresh threads offered slots (the web channel
    already does). Source-level check: both voice prompt-build sites reference
    ``get_offered_slots``. Advisory until f3 lands."""
    try:
        from app.voice import bot as voice_bot
        from app.voice import processors as voice_processors
    except Exception:
        return {"enforced": PHONE_OFFERED_SLOTS_ENFORCED, "available": False, "pass": False}

    processors_src = py_inspect.getsource(voice_processors)
    bot_src = py_inspect.getsource(voice_bot)
    threaded = "get_offered_slots" in processors_src and "get_offered_slots" in bot_src
    return {"enforced": PHONE_OFFERED_SLOTS_ENFORCED, "available": True, "pass": threaded}


def probe_r_confirm(contract_text: str | None = None) -> dict:
    """R-CONFIRM: verbal confirmation of the appointment details before concluding —
    contract text now; the deterministic transcript check joins the gate at q2."""
    from app.agent import prompts

    contract = contract_text if contract_text is not None else prompts.SCHEDULING_CONTRACT

    checks = {
        "contract_readback": "read back the chosen technician + date + time" in contract,
        "contract_appointment_id": "read the `appointment_id` back" in contract,
        "contract_slot_taken_alternatives": (
            "slot_taken" in contract and "never silently retry" in contract
        ),
    }

    readback_fixture = _subcheck_readback_fixture()
    explicit_appliance = _subcheck_explicit_appliance_param()

    enforced_ok = all(
        sub["pass"] for sub in (readback_fixture, explicit_appliance) if sub["enforced"]
    )
    return {
        "checks": checks,
        "readback_fixture": readback_fixture,
        "explicit_appliance_param": explicit_appliance,
        "budget": {"all_enforced_checks": True},
        "pass": all(checks.values()) and enforced_ok,
    }


def _subcheck_readback_fixture() -> dict:
    """q2: the deterministic read-back assertion, run against the committed positive
    fixture (must PASS) and the no-read-back canary (must FAIL — the mutation
    detector). Reports its inputs honestly while advisory; hard-requires them once
    enforced."""
    from evals.scenarios.schema import ScenarioAssert

    result: dict[str, Any] = {
        "enforced": READBACK_FIXTURE_ENFORCED,
        "assertion_available": "readback" in ScenarioAssert.model_fields,
        "positive_fixture_pass": False,
        "canary_fixture_fails": False,
    }
    if not result["assertion_available"]:
        result["pass"] = False
        return result

    from evals.assertions import check_structural_assertions

    positive_scenario = _load_scenario("hermetic/scheduling/readback_confirmation_details.yaml")
    canary_scenario = _load_scenario("canaries/booking_no_readback.yaml")
    positive_fixture = _load_fixture("scheduling_readback_confirmation_details.json")
    canary_fixture = _load_fixture("canary_booking_no_readback.json")
    if None in (positive_scenario, canary_scenario, positive_fixture, canary_fixture):
        result["fixture_missing"] = True
        result["pass"] = False
        return result
    if positive_scenario.assert_.readback is None or canary_scenario.assert_.readback is None:
        result["scenario_not_wired"] = True
        result["pass"] = False
        return result

    result["positive_fixture_pass"] = check_structural_assertions(
        positive_scenario, positive_fixture
    ).ok
    result["canary_fixture_fails"] = not check_structural_assertions(
        canary_scenario, canary_fixture
    ).ok
    result["pass"] = result["positive_fixture_pass"] and result["canary_fixture_fails"]
    return result


def _subcheck_explicit_appliance_param() -> dict:
    """f2: `book_appointment` accepts an explicit ``appliance_type`` instead of
    relying solely on keyword inference from ``issue_summary``. Advisory until f2."""
    from app.tools.scheduling_tools import book_appointment

    has_param = "appliance_type" in py_inspect.signature(book_appointment).parameters
    return {"enforced": EXPLICIT_APPLIANCE_PARAM_ENFORCED, "pass": has_param}


def probe_r_memory() -> dict:
    """Tier 1 never-re-ask: the prompt rules exist AND the structural detector
    actually fires — the committed fixture passes, a synthetic violating one fails."""
    from app.agent import prompts
    from evals.assertions import check_structural_assertions

    checks = {
        "never_reask_rule": "NEVER RE-ASK" in prompts.NON_NEGOTIABLES,
        "zip_never_reask_rule": "never re-ask for the zip" in prompts.SCHEDULING_CONTRACT,
    }

    scenario = _load_scenario("scheduling/zip_never_reasked.yaml")
    fixture = _load_fixture("scheduling_zip_never_reasked.json")
    if scenario is None or fixture is None:
        checks["fixture_no_reask_pass"] = False
        checks["violating_fixture_detected"] = False
    else:
        checks["fixture_no_reask_pass"] = check_structural_assertions(scenario, fixture).ok
        violating = json.loads(json.dumps(fixture))
        violating.setdefault("flags", {})["reasked_fields"] = ["customer.zip"]
        checks["violating_fixture_detected"] = not check_structural_assertions(
            scenario, violating
        ).ok

    return {"checks": checks, "budget": {"all_checks": True}, "pass": all(checks.values())}


async def probe_db_live() -> dict:
    """ADVISORY: seeded row counts + one live matching smoke on the real Postgres.
    Skipped without a reachable ``DATABASE_URL``; never affects ``overall_pass``."""
    if not os.environ.get("DATABASE_URL"):
        return {"status": "skipped", "detail": {"reason": "DATABASE_URL not set"}}

    from sqlalchemy import distinct, func, select

    from app.db.matching import find_technician_matches, session_scope
    from app.db.models_scheduling import AvailabilitySlot, ServiceArea, Specialty, Technician

    async def _smoke() -> dict:
        async with session_scope() as session:
            techs = (await session.execute(select(func.count(Technician.id)))).scalar()
            specialties = (await session.execute(select(func.count(Specialty.id)))).scalar()
            zips = (
                await session.execute(select(func.count(distinct(ServiceArea.zip_code))))
            ).scalar()
            open_future = (
                await session.execute(
                    select(func.count(AvailabilitySlot.id)).where(
                        AvailabilitySlot.status == "open",
                        AvailabilitySlot.starts_at > datetime.now(UTC),
                    )
                )
            ).scalar()
            matches = await find_technician_matches(session, "60614", "washer")
            return {
                "technicians": techs,
                "specialties": specialties,
                "distinct_zips": zips,
                "open_future_slots": open_future,
                "match_60614_washer": len(matches),
            }

    try:
        detail = await asyncio.wait_for(_smoke(), timeout=15)
    except Exception as exc:  # advisory lane: report, never crash the bench
        return {"status": "fail", "detail": {"error": f"{type(exc).__name__}: {exc}"}}

    ok = (
        (detail["technicians"] or 0) >= MIN_TECHNICIANS
        and (detail["distinct_zips"] or 0) >= MIN_DISTINCT_ZIPS
        and (detail["open_future_slots"] or 0) > 0
    )
    return {"status": "pass" if ok else "fail", "detail": detail}


# --- report assembly + gate -----------------------------------------------------------


def build_report(probes: dict[str, dict], advisory: dict[str, dict] | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "probes": probes,
        "advisory": advisory or {},
        "overall_pass": all(p.get("pass") for p in probes.values()),
    }


async def run_bench() -> dict:
    probes = {
        "r_db_schema": probe_r_db_schema(),
        "r_seed": probe_r_seed(),
        "r_match": await probe_r_match(),
        "r_flow": probe_r_flow(),
        "r_confirm": probe_r_confirm(),
        "r_memory": probe_r_memory(),
    }
    advisory = {"db_live": await probe_db_live()}
    return build_report(probes, advisory)


def _advisory_subchecks(probe: dict) -> list[str]:
    return [
        name
        for name, sub in probe.items()
        if isinstance(sub, dict) and sub.get("enforced") is False
    ]


def main() -> None:
    report = asyncio.run(run_bench())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    for name, probe in report["probes"].items():
        verdict = "PASS" if probe["pass"] else "FAIL"
        advisory_subs = _advisory_subchecks(probe)
        extra = f" (advisory sub-checks: {', '.join(advisory_subs)})" if advisory_subs else ""
        print(f"appt-req-bench {name}: {verdict}{extra}")
    db_live = report["advisory"]["db_live"]
    print(f"appt-req-bench db_live: {db_live['status'].upper()} (advisory)")
    print(f"appt-req-bench overall: {'PASS' if report['overall_pass'] else 'FAIL'} -> {out_path}")

    # Soft gate until the loop's terminal gate-flip earns APPT_REQ_GATE_HARD default 1.
    if not report["overall_pass"] and os.environ.get("APPT_REQ_GATE_HARD", "0") == "1":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
