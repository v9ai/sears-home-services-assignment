"""Booking-bench harness guards (bugfix-loop T5) — hermetic half.

Covers the two documented footguns of `scripts/booking_quality_bench.py` that
had zero coverage: ToolWiretap must not rewrite the LLM-visible tool schema
(the hard-won 2026-07-09 lesson — a `*args` wrapper silently breaks function
calling), and the aggregate `overall_pass` gate must fail on any scenario
failure, tool exception, or unknown-id error. The DB self-cleanup half lives
in tests/scheduling/test_bench_cleanup.py (needs Postgres).
"""

from __future__ import annotations

import inspect

import pytest

import app.tools.scheduling_tools as st
from scripts.booking_quality_bench import ToolWiretap, aggregate_results


@pytest.fixture(autouse=True)
def _restore_scheduling_module():
    """ToolWiretap mutates module globals (functions + TOOLS); a leaked mutation
    contaminates the registry-facing suites (found the hard way in i11's first
    gate run). Snapshot and restore everything, whatever the test does."""
    snapshot = (st.find_technicians, st.book_appointment, list(st.TOOLS))
    yield
    st.find_technicians, st.book_appointment = snapshot[0], snapshot[1]
    st.TOOLS = snapshot[2]


def _result(**overrides) -> dict:
    base = {
        "pass": True,
        "booked": True,
        "tool_calls": [],
        "reasked_fields": [],
        "nudges": 0,
    }
    return {**base, **overrides}


# --- ToolWiretap schema preservation ------------------------------------------


def test_wiretap_preserves_signatures_and_annotations() -> None:
    orig_find, orig_book = st.find_technicians, st.book_appointment
    wiretap = ToolWiretap()
    wiretap.install()
    try:
        for wrapped, origin in (
            (st.find_technicians, orig_find),
            (st.book_appointment, orig_book),
        ):
            wrapped_sig = inspect.signature(wrapped)
            origin_sig = inspect.signature(origin)
            assert list(wrapped_sig.parameters) == list(origin_sig.parameters), (
                "wiretap wrapper changed the LLM-visible parameter list"
            )
            assert not any(
                p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                for p in wrapped_sig.parameters.values()
            ), "wiretap wrapper must not use *args/**kwargs (2026-07-09 lesson)"
            assert wrapped.__annotations__ == origin.__annotations__
            assert wrapped.__doc__ == origin.__doc__
        assert st.TOOLS == [st.find_technicians, st.book_appointment]
    finally:
        wiretap.uninstall()


def test_wiretap_uninstall_restores_the_originals() -> None:
    orig_find, orig_book = st.find_technicians, st.book_appointment
    wiretap = ToolWiretap()
    wiretap.install()
    assert st.find_technicians is not orig_find
    wiretap.uninstall()
    assert st.find_technicians is orig_find
    assert st.book_appointment is orig_book
    assert st.TOOLS == [orig_find, orig_book]


async def test_wiretap_records_offers_and_fires_conflict_arm_once(monkeypatch) -> None:
    offered = '{"technicians": [{"slots": [{"slot_id": "s1"}, {"slot_id": "s2"}]}]}'

    async def fake_find(zip, appliance_type, window=None):  # noqa: A002
        return offered

    async def fake_book(slot_id, customer, issue_summary):
        return '{"status": "error", "message": "No slot with id nope"}'

    monkeypatch.setattr(st, "find_technicians", fake_find)
    monkeypatch.setattr(st, "book_appointment", fake_book)
    wiretap = ToolWiretap()
    claims: list[str] = []

    async def fake_claim(slot_id: str) -> None:
        claims.append(slot_id)

    wiretap._claim_out_of_band = fake_claim
    wiretap.install()
    try:
        wiretap.reset_for_scenario(conflict=True)
        await st.find_technicians("60601", "washer")
        await st.find_technicians("60601", "washer")
        assert wiretap.offered_slot_ids == ["s1", "s2", "s1", "s2"]
        assert claims == ["s1"], "conflict arm must fire exactly once, on the first offer"

        await st.book_appointment("nope", None, "washer broken")
        book_calls = [c for c in wiretap.calls if c["tool"] == "book_appointment"]
        assert book_calls[-1].get("unknown_id") is True
    finally:
        wiretap.uninstall()


# --- aggregate overall_pass gate ------------------------------------------------


def test_all_green_aggregate_passes() -> None:
    aggregate, overall = aggregate_results([_result(), _result()])
    assert overall is True
    assert aggregate["scenarios_pass"] == 2 and aggregate["scenarios_total"] == 2


def test_one_failing_scenario_fails_overall() -> None:
    _, overall = aggregate_results([_result(), _result(**{"pass": False})])
    assert overall is False


def test_tool_exception_fails_overall_even_if_scenarios_pass() -> None:
    bad = _result(tool_calls=[{"tool": "find_technicians", "exception": "OperationalError"}])
    aggregate, overall = aggregate_results([bad])
    assert aggregate["tool_exception_count"] == 1
    assert overall is False


def test_unknown_id_error_fails_overall() -> None:
    bad = _result(tool_calls=[{"tool": "book_appointment", "unknown_id": True}])
    aggregate, overall = aggregate_results([bad])
    assert aggregate["unknown_id_errors"] == 1
    assert overall is False


def test_reasks_and_nudges_are_reported_but_do_not_gate() -> None:
    noisy = _result(reasked_fields=["zip"], nudges=3)
    aggregate, overall = aggregate_results([noisy])
    assert aggregate["reask_violations"] == 1 and aggregate["total_nudges"] == 3
    assert overall is True
