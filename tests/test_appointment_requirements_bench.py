"""Appointment-requirements bench tests (appointment-requirements-iterate q1) — pin
the schema and run the probes in-process so `make test` alone catches bench rot.

The bench (`scripts/appointment_requirements_bench.py`) is the appointment-requirements
loop's metric: six hermetic probes encoding the take-home spec's Tier 2 scheduling
requirements (+ Tier 1 never-re-ask). These tests assert the probe verdicts against
the CURRENT schema/seed/contract, and — via the probes' injectable inputs — that each
probe actually DETECTS a violation (mutation cases), so a probe can never rot into a
tautology.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
import sqlalchemy as sa

from scripts import appointment_requirements_bench as bench

REQUIRED_PROBE_KEYS = {"budget", "pass"}
EXPECTED_PROBES = {"r_db_schema", "r_seed", "r_match", "r_flow", "r_confirm", "r_memory"}


# --- probes against the current schema / seed / contract ---------------------------


def test_r_db_schema_passes_on_current_models():
    probe = bench.probe_r_db_schema()
    assert probe["checks"] == {check: True for check in probe["checks"]}
    assert probe["pass"] is True


def test_r_seed_passes_on_current_seed():
    probe = bench.probe_r_seed()
    assert probe["technicians"] >= bench.MIN_TECHNICIANS
    assert probe["distinct_zips"] >= bench.MIN_DISTINCT_ZIPS
    assert probe["metro_clusters"] >= bench.MIN_METRO_CLUSTERS
    assert probe["pass"] is True


async def test_r_match_passes_on_production_query():
    probe = await bench.probe_r_match()
    assert probe["checks"] == {check: True for check in probe["checks"]}
    assert probe["pass"] is True


def test_r_flow_passes_with_advisory_subchecks():
    probe = bench.probe_r_flow()
    assert all(probe["checks"].values()), probe["checks"]
    # Sub-checks stay advisory until their owning fix flips them (f1 / f3):
    # flipping `enforced` without the fix is forbidden by the loop protocol §0.
    for sub in ("zip_validation", "phone_offered_slots"):
        assert "enforced" in probe[sub] and "pass" in probe[sub]
    assert probe["pass"] is True


def test_r_confirm_passes_with_advisory_subchecks():
    probe = bench.probe_r_confirm()
    assert all(probe["checks"].values()), probe["checks"]
    for sub in ("readback_fixture", "explicit_appliance_param"):
        assert "enforced" in probe[sub] and "pass" in probe[sub]
    assert probe["pass"] is True


def test_r_memory_detector_fires_on_violation():
    """The probe itself proves the never-re-ask detector both passes the committed
    fixture AND fails a synthetic violating one — a dead detector fails the probe."""
    probe = bench.probe_r_memory()
    assert probe["checks"]["fixture_no_reask_pass"] is True
    assert probe["checks"]["violating_fixture_detected"] is True
    assert probe["pass"] is True


async def test_run_bench_runs_all_probes_and_passes():
    report = await bench.run_bench()
    assert set(report["probes"]) == EXPECTED_PROBES
    assert report["overall_pass"] is True
    assert all(p["pass"] for p in report["probes"].values())
    assert report["advisory"]["db_live"]["status"] in {"skipped", "pass", "fail"}


# --- mutation cases: every probe must FAIL on a violating input ---------------------


def test_r_seed_fails_on_too_few_technicians():
    from app.db.seed import TECHNICIANS

    probe = bench.probe_r_seed(technicians=TECHNICIANS[:3])
    assert probe["checks"]["min_technicians"] is False
    assert probe["pass"] is False


@dataclass(frozen=True)
class _StubTech:
    name: str
    email: str
    zips: tuple[str, ...]
    specialties: tuple[str, ...]


def test_r_seed_fails_on_single_metro_cluster():
    techs = tuple(
        _StubTech(f"T{i}", f"t{i}@x.example", (f"6060{i}",), ("washer", "dryer")) for i in range(6)
    )
    probe = bench.probe_r_seed(technicians=techs)
    assert probe["checks"]["min_clusters"] is False
    assert probe["pass"] is False


def test_r_seed_fails_on_uncovered_specialty():
    from app.db.seed import TECHNICIANS

    stripped = tuple(
        _StubTech(
            t.name,
            t.email,
            t.zips,
            tuple(s for s in t.specialties if s != "hvac") or ("washer",),
        )
        for t in TECHNICIANS
    )
    probe = bench.probe_r_seed(technicians=stripped)
    assert probe["checks"]["specialties_covered"] is False
    assert probe["pass"] is False


def test_r_db_schema_fails_without_slot_unique_constraint():
    """A metadata missing the assignment's double-booking guard must fail the probe."""
    metadata = sa.MetaData()
    sa.Table("technicians", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table("specialties", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table("technician_specialties", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table("service_areas", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table(
        "availability_slots",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("technician_id", sa.String),
        sa.Column("starts_at", sa.DateTime),
        sa.Column("status", sa.String),
        # no UNIQUE(technician_id, starts_at)
    )
    sa.Table("appointments", metadata, sa.Column("id", sa.String, primary_key=True))
    probe = bench.probe_r_db_schema(metadata=metadata)
    assert probe["checks"]["tables"] is True  # tables exist, guards don't
    assert probe["checks"]["slot_unique"] is False
    assert probe["checks"]["appointment_fks"] is False
    assert probe["pass"] is False


def test_r_confirm_fails_without_readback_sentence():
    from app.agent.prompts import SCHEDULING_CONTRACT

    stripped = SCHEDULING_CONTRACT.replace(
        "read back the chosen technician + date + time", "book it"
    )
    probe = bench.probe_r_confirm(contract_text=stripped)
    assert probe["checks"]["contract_readback"] is False
    assert probe["pass"] is False


def test_r_flow_fails_without_three_option_cap():
    from app.agent.prompts import SCHEDULING_CONTRACT

    stripped = SCHEDULING_CONTRACT.replace("at most 3 options", "some options")
    probe = bench.probe_r_flow(contract_text=stripped)
    assert probe["checks"]["contract_max_three"] is False
    assert probe["pass"] is False


# --- report assembly + gate wiring --------------------------------------------------


def test_build_report_schema_and_overall_pass_logic():
    probes = {
        "r_seed": {"budget": {}, "pass": True},
        "r_confirm": {"budget": {}, "pass": True},
    }
    report = bench.build_report(probes, advisory={"db_live": {"status": "skipped"}})
    assert report["schema_version"] == 1
    assert report["timestamp_utc"].endswith("Z")
    assert report["overall_pass"] is True
    for probe in report["probes"].values():
        assert REQUIRED_PROBE_KEYS <= set(probe)

    probes["r_confirm"]["pass"] = False
    assert bench.build_report(probes)["overall_pass"] is False


def test_advisory_never_affects_overall_pass():
    probes = {"r_seed": {"budget": {}, "pass": True}}
    report = bench.build_report(probes, advisory={"db_live": {"status": "fail"}})
    assert report["overall_pass"] is True


def _canned_failing_report():
    return bench.build_report(
        {name: {"budget": {}, "pass": name != "r_confirm"} for name in EXPECTED_PROBES},
        advisory={"db_live": {"status": "skipped"}},
    )


def test_soft_gate_default_reports_only(monkeypatch, tmp_path, capsys):
    """Report-only until the loop's terminal gate-flip: a failing report writes +
    prints but never exits nonzero by default."""

    async def _canned_bench():
        return _canned_failing_report()

    monkeypatch.setattr(bench, "run_bench", _canned_bench)
    monkeypatch.setattr(bench, "OUT_DIR", tmp_path)
    monkeypatch.delenv("APPT_REQ_GATE_HARD", raising=False)

    bench.main()  # no SystemExit

    assert "appt-req-bench overall: FAIL" in capsys.readouterr().out
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_hard_gate_exits_nonzero_on_fail(monkeypatch, tmp_path):
    async def _canned_bench():
        return _canned_failing_report()

    monkeypatch.setattr(bench, "run_bench", _canned_bench)
    monkeypatch.setattr(bench, "OUT_DIR", tmp_path)
    monkeypatch.setenv("APPT_REQ_GATE_HARD", "1")

    with pytest.raises(SystemExit) as excinfo:
        bench.main()
    assert excinfo.value.code == 1


def test_main_writes_report_and_prints_advisory_subchecks(monkeypatch, tmp_path, capsys):
    canned = bench.build_report(
        {
            "r_confirm": {
                "checks": {"contract_readback": True},
                "readback_fixture": {"enforced": False, "pass": False},
                "budget": {},
                "pass": True,
            }
        },
        advisory={"db_live": {"status": "skipped"}},
    )

    async def _canned_bench():
        return canned

    monkeypatch.setattr(bench, "run_bench", _canned_bench)
    monkeypatch.setattr(bench, "OUT_DIR", tmp_path)
    monkeypatch.delenv("APPT_REQ_GATE_HARD", raising=False)

    bench.main()

    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text()) == canned
    out = capsys.readouterr().out
    assert "r_confirm: PASS (advisory sub-checks: readback_fixture)" in out
    assert "db_live: SKIPPED (advisory)" in out
