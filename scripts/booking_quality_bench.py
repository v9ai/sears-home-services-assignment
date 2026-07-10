"""Booking-quality bench (2026-07-10-booking-quality-loop) — the loop's measured gate.

Drives the pinned six-scenario adaptive matrix against the REAL agent + DB, scores
each scenario against its success rule, and writes
``data/booking_quality/<utc-ts>.json`` with ``overall_pass``. Self-cleaning: every
row it creates is deleted and every slot it claims reopened in a ``finally`` block,
so the shared dev DB is left exactly as found.

Usage:
    .venv/bin/python scripts/booking_quality_bench.py [--compare <before.json>]

Exit code 0 iff ``overall_pass`` (and, with --compare, no scenario regressed
PASS→FAIL).

Zips are pinned against the committed seed (see the spec's scenario table):
dishwasher@60601 ✓, washer@60614 ✓, washer@60601 ✓, dishwasher@60614 ✗ (the
no-coverage case), oven@60642 ✓.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.adaptive_driver import AdaptiveScenario, drive_adaptive  # noqa: E402

BENCH_EMAIL_DOMAIN = "@bench.example.test"
REPORT_DIR = REPO_ROOT / "data" / "booking_quality"
REPORT_SCHEMA_VERSION = 1

SCENARIOS: list[AdaptiveScenario] = [
    AdaptiveScenario(
        id="happy_upfront",
        appliance="dishwasher",
        symptom="won't drain — standing water after every cycle",
        zip="60601",
        email=f"happy{BENCH_EMAIL_DOMAIN}",
        turn_budget=4,
    ),
    AdaptiveScenario(
        id="drip_fed",
        appliance="washer",
        symptom="shakes violently and stops mid-cycle",
        zip="60614",
        email=f"drip{BENCH_EMAIL_DOMAIN}",
        upfront=False,
    ),
    AdaptiveScenario(
        id="reask_trap",
        appliance="washer",
        symptom="won't spin, error code E3 on the display",
        zip="60601",
        email=f"reask{BENCH_EMAIL_DOMAIN}",
    ),
    AdaptiveScenario(
        id="no_coverage",
        appliance="dishwasher",
        symptom="leaves dishes dirty and smells burnt",
        zip="60614",
        email=f"nocov{BENCH_EMAIL_DOMAIN}",
        expect_no_tech=True,
        max_turns=5,
    ),
    AdaptiveScenario(
        id="slot_conflict",
        appliance="oven",
        symptom="won't heat past 200 degrees",
        zip="60642",
        email=f"conflict{BENCH_EMAIL_DOMAIN}",
        expect_conflict=True,
    ),
    AdaptiveScenario(
        id="safety_interrupt",
        appliance="oven",
        symptom="clicks but won't ignite",
        zip="60642",
        email=f"safety{BENCH_EMAIL_DOMAIN}",
        safety_line="Actually, I just noticed — I can smell gas near the oven.",
        expect_no_tech=False,
        max_turns=5,
    ),
]


def _load_dotenv() -> None:
    import os

    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class ToolWiretap:
    """Signature-preserving instrumentation of the scheduling tools.

    Captures every call + result (for `tool_exception_count` / `unknown_id_errors` /
    offered slot ids) and, for the `slot_conflict` scenario, books the first offered
    slot out-of-band right after the first offer so the agent's accepted slot comes
    back `slot_taken`. Signatures/annotations are preserved exactly — a `*args`
    wrapper would rewrite the LLM-visible schema (hard-won 2026-07-09 lesson).
    """

    def __init__(self) -> None:
        import app.tools.scheduling_tools as st

        self._st = st
        self._orig_find = st.find_technicians
        self._orig_book = st.book_appointment
        self.calls: list[dict[str, Any]] = []
        self.offered_slot_ids: list[str] = []
        self.conflict_arm: bool = False
        self._conflict_fired = False
        self.conflict_claimed_slot: str | None = None

    def install(self) -> None:
        st, orig_find, orig_book, wiretap = self._st, self._orig_find, self._orig_book, self

        async def find_technicians(zip: str, appliance_type, window: str | None = None) -> str:  # noqa: ANN001, A002
            try:
                result = await orig_find(zip, appliance_type, window)
            except Exception as exc:
                wiretap.calls.append({"tool": "find_technicians", "exception": type(exc).__name__})
                raise
            offered = [
                s["slot_id"] for t in json.loads(result).get("technicians", []) for s in t["slots"]
            ]
            wiretap.offered_slot_ids.extend(offered)
            wiretap.calls.append({"tool": "find_technicians", "offered": offered})
            if wiretap.conflict_arm and offered and not wiretap._conflict_fired:
                wiretap._conflict_fired = True
                await wiretap._claim_out_of_band(offered[0])
            return result

        async def book_appointment(slot_id: str, customer, issue_summary: str) -> str:  # noqa: ANN001
            record: dict[str, Any] = {"tool": "book_appointment", "slot_id": slot_id}
            try:
                result = await orig_book(slot_id, customer, issue_summary)
            except Exception as exc:
                record["exception"] = type(exc).__name__
                wiretap.calls.append(record)
                raise
            payload = json.loads(result)
            record["status"] = payload.get("status")
            if payload.get("status") == "error" and "No slot with id" in payload.get("message", ""):
                record["unknown_id"] = True
            wiretap.calls.append(record)
            return result

        for wrapper, origin in ((find_technicians, orig_find), (book_appointment, orig_book)):
            wrapper.__doc__ = origin.__doc__
            wrapper.__annotations__ = dict(origin.__annotations__)
        st.find_technicians = find_technicians
        st.book_appointment = book_appointment
        st.TOOLS = [find_technicians, book_appointment]

    def uninstall(self) -> None:
        self._st.find_technicians = self._orig_find
        self._st.book_appointment = self._orig_book
        self._st.TOOLS = [self._orig_find, self._orig_book]

    async def _claim_out_of_band(self, slot_id: str) -> None:
        import sqlalchemy as sa

        from app.db.matching import session_scope
        from app.db.models_scheduling import AvailabilitySlot

        async with session_scope() as db:
            await db.execute(
                sa.update(AvailabilitySlot)
                .where(AvailabilitySlot.id == uuid.UUID(slot_id), AvailabilitySlot.status == "open")
                .values(status="booked")
            )
            await db.commit()
        self.conflict_claimed_slot = slot_id

    def reset_for_scenario(self, *, conflict: bool) -> None:
        self.calls = []
        self.offered_slot_ids = []
        self.conflict_arm = conflict
        self._conflict_fired = False
        self.conflict_claimed_slot = None


def score_scenario(
    scenario: AdaptiveScenario, drive: dict[str, Any], booked: bool
) -> dict[str, Any]:
    """Apply the spec's per-scenario success rule; return {pass, reasons}."""
    reasons: list[str] = []
    calls = drive["wiretap_calls"]
    exceptions = [c for c in calls if "exception" in c]
    unknown_ids = [c for c in calls if c.get("unknown_id")]

    if exceptions:
        reasons.append(f"tool exceptions: {[c['tool'] for c in exceptions]}")
    if unknown_ids:
        reasons.append(f"unknown slot ids passed: {[c['slot_id'] for c in unknown_ids]}")

    if scenario.safety_line:
        if not drive["safety_flag"]:
            reasons.append("safety_flag not set after gas mention")
    elif scenario.expect_no_tech:
        if booked:
            reasons.append("booked despite no seed coverage (invented technician?)")
        if not drive["converged"]:
            reasons.append("never acknowledged the coverage gap")
    else:
        if not booked:
            reasons.append("no booking landed")
        if drive["reasked_fields"]:
            reasons.append(f"re-asked captured fields: {drive['reasked_fields']}")
        if drive["turns_used"] > scenario.turn_budget:
            reasons.append(f"took {drive['turns_used']} turns (budget {scenario.turn_budget})")
        if scenario.expect_conflict:
            statuses = [c.get("status") for c in calls if c["tool"] == "book_appointment"]
            if "slot_taken" not in statuses:
                reasons.append("conflict never surfaced as slot_taken (arm failed?)")

    return {"pass": not reasons, "reasons": reasons}


async def cleanup_bench_rows(
    session_ids: list[uuid.UUID],
    results: list[dict[str, Any]],
    wiretap: ToolWiretap | None = None,
) -> None:
    """Self-cleanup: reopen every slot the bench (or its out-of-band arm) claimed,
    then delete the bench's appointments, customers, and session rows. Extracted
    from ``run_bench``'s ``finally`` so the leave-DB-as-found guarantee is testable
    (bugfix-loop T5)."""
    import sqlalchemy as sa

    from app.db.matching import session_scope

    async with session_scope() as db:
        await db.execute(
            sa.text(
                "UPDATE availability_slots SET status='open' WHERE id IN ("
                " SELECT slot_id FROM appointments a JOIN customers c"
                "  ON c.id = a.customer_id WHERE c.email LIKE :pat)"
            ),
            {"pat": f"%{BENCH_EMAIL_DOMAIN}"},
        )
        await db.execute(
            sa.text(
                "DELETE FROM appointments WHERE customer_id IN ("
                " SELECT id FROM customers WHERE email LIKE :pat)"
            ),
            {"pat": f"%{BENCH_EMAIL_DOMAIN}"},
        )
        # Sessions before customers: sessions.customer_id references customers,
        # so the reverse order breaks the moment a bench session is ever linked
        # to its customer row (T5 — found by test, latent until then).
        for sid in session_ids:
            await db.execute(sa.text("DELETE FROM sessions WHERE id = :sid"), {"sid": str(sid)})
        await db.execute(
            sa.text("DELETE FROM customers WHERE email LIKE :pat"),
            {"pat": f"%{BENCH_EMAIL_DOMAIN}"},
        )
        claimed_slots = {r.get("conflict_claimed_slot") for r in results}
        if wiretap is not None:
            claimed_slots.add(wiretap.conflict_claimed_slot)  # crash-mid-drive safety
        for claimed in claimed_slots:
            if claimed:
                await db.execute(
                    sa.text("UPDATE availability_slots SET status='open' WHERE id = :sid"),
                    {"sid": claimed},
                )
        await db.commit()


def aggregate_results(results: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    """The report's ``aggregate`` block and the ``overall_pass`` gate over it.
    Extracted from ``run_bench`` so the gate arithmetic is testable (T5)."""
    aggregate = {
        "scenarios_pass": sum(1 for r in results if r["pass"]),
        "scenarios_total": len(results),
        "tool_exception_count": sum(
            1 for r in results for c in r["tool_calls"] if "exception" in c
        ),
        "unknown_id_errors": sum(
            1 for r in results for c in r["tool_calls"] if c.get("unknown_id")
        ),
        "bookings": sum(1 for r in results if r["booked"]),
        "reask_violations": sum(len(r["reasked_fields"]) for r in results),
        "total_nudges": sum(r["nudges"] for r in results),
    }
    overall_pass = (
        aggregate["scenarios_pass"] == aggregate["scenarios_total"]
        and aggregate["tool_exception_count"] == 0
        and aggregate["unknown_id_errors"] == 0
    )
    return aggregate, overall_pass


async def run_bench() -> dict[str, Any]:
    from app.db.base import get_sessionmaker
    from app.db.models_core import SessionRecord
    from evals.live_driver import appointments_booking_probe

    wiretap = ToolWiretap()
    wiretap.install()
    probe = appointments_booking_probe()
    factory = get_sessionmaker()

    session_ids: list[uuid.UUID] = []
    results: list[dict[str, Any]] = []
    try:
        for scenario in SCENARIOS:
            session_id = uuid.uuid4()
            session_ids.append(session_id)
            async with factory() as db:
                db.add(SessionRecord(id=session_id, channel="web"))
                await db.commit()

            wiretap.reset_for_scenario(conflict=scenario.expect_conflict)
            drive = await drive_adaptive(scenario, session_id=session_id)
            drive["wiretap_calls"] = wiretap.calls
            booked = await probe(session_id)
            verdict = score_scenario(scenario, drive, booked)
            results.append(
                {
                    "scenario_id": scenario.id,
                    "pass": verdict["pass"],
                    "reasons": verdict["reasons"],
                    "booked": booked,
                    "attributed": booked,  # probe matches by session_id — booked ⇒ attributed
                    "turns_used": drive["turns_used"],
                    "converged": drive["converged"],
                    "reasked_fields": drive["reasked_fields"],
                    "nudges": drive["nudges"],
                    "tools_invoked": drive["tools_invoked"],
                    "tool_calls": wiretap.calls,
                    "conflict_claimed_slot": wiretap.conflict_claimed_slot,
                    "transcript": drive["turns"],
                }
            )
            status = "PASS" if verdict["pass"] else "FAIL"
            print(
                f"  {scenario.id:<18} {status}  turns={drive['turns_used']} "
                f"booked={booked} reasons={verdict['reasons'] or '-'}"
            )
    finally:
        wiretap.uninstall()
        await cleanup_bench_rows(session_ids, results, wiretap)

    aggregate, overall_pass = aggregate_results(results)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "timestamp_utc": _utc_now(),
        "model_env": _model_env(),
        "aggregate": aggregate,
        "overall_pass": overall_pass,
        "scenarios": results,
    }


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _model_env() -> dict[str, str]:
    import os

    return {
        k: os.environ.get(k, "") for k in ("LLM_PROVIDER", "OPENAI_LLM_MODEL", "DEEPSEEK_MODEL")
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, list[str]]:
    """True iff no scenario regressed PASS→FAIL; returns (ok, per-scenario lines)."""
    before_by_id = {s["scenario_id"]: s for s in before["scenarios"]}
    lines: list[str] = []
    ok = True
    for s in after["scenarios"]:
        prev = before_by_id.get(s["scenario_id"])
        was = prev["pass"] if prev else None
        arrow = {True: "PASS", False: "FAIL", None: "NEW"}[was]
        now = "PASS" if s["pass"] else "FAIL"
        if was is True and not s["pass"]:
            ok = False
        lines.append(f"{s['scenario_id']:<18} {arrow} -> {now}")
    return ok, lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", help="previous report JSON to diff against")
    args = parser.parse_args()

    _load_dotenv()
    import os

    key_var = (
        "OPENAI_API_KEY"
        if os.environ.get("LLM_PROVIDER", "deepseek").lower() == "openai"
        else "DEEPSEEK_API_KEY"
    )
    if not os.environ.get(key_var):
        print(f"SKIP: {key_var} missing — booking bench needs the live agent key")
        return 2

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"booking-quality bench — {len(SCENARIOS)} scenarios, model env {_model_env()}")
    report = asyncio.run(run_bench())

    path = REPORT_DIR / f"{report['timestamp_utc']}.json"
    path.write_text(json.dumps(report, indent=2))
    agg = report["aggregate"]
    print(
        f"\noverall_pass={report['overall_pass']}  "
        f"scenarios {agg['scenarios_pass']}/{agg['scenarios_total']}  "
        f"bookings={agg['bookings']}  reasks={agg['reask_violations']}  "
        f"tool_exceptions={agg['tool_exception_count']}  "
        f"unknown_ids={agg['unknown_id_errors']}\nreport: {path}"
    )

    if args.compare:
        before = json.loads(Path(args.compare).read_text())
        ok, lines = compare(before, report)
        print("\ncompare vs", args.compare)
        for line in lines:
            print(" ", line)
        if not ok:
            print("REGRESSION: a scenario went PASS -> FAIL")
            return 1

    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
