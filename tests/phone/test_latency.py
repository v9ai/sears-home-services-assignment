"""Latency instrumentation unit tests (plan.md group 5: end-of-speech -> first-audio,
phone e2e budget per specs/latency/budgets.md)."""

import logging

import pytest

from app.latency.budgets import PHONE_E2E
from app.phone.latency import P50_BUDGET_S, P95_BUDGET_S, LatencyRecorder, percentile


def test_within_budget_true_when_no_samples():
    assert LatencyRecorder().within_budget() is True


def test_within_budget_true_for_samples_inside_budget():
    rec = LatencyRecorder()
    for s in [0.5, 1.0, 1.5, 2.0, 2.4]:
        rec.record(s)
    assert rec.p50 <= P50_BUDGET_S
    assert rec.p95 <= P95_BUDGET_S
    assert rec.within_budget() is True


def test_within_budget_false_when_p95_exceeds_budget():
    rec = LatencyRecorder()
    for s in [0.5, 0.6, 0.7, 0.8, 5.0]:  # one outlier busts p95
        rec.record(s)
    assert rec.within_budget() is False


def test_record_logs_warning_over_p95_and_info_otherwise(caplog):
    rec = LatencyRecorder()
    with caplog.at_level(logging.INFO, logger="app.phone.latency"):
        rec.record(1.0)
        rec.record(4.5)
    levels = [r.levelno for r in caplog.records]
    assert logging.INFO in levels
    assert logging.WARNING in levels


def test_budgets_sourced_from_central_module():
    # Local reinforcement of tests/latency/test_budget_spec_sync.py: the aliases must
    # track app/latency/budgets.py, never a re-hardcoded literal.
    assert P50_BUDGET_S == PHONE_E2E.p50_s
    assert P95_BUDGET_S == PHONE_E2E.p95_s


@pytest.mark.parametrize(
    ("samples", "p", "expected"),
    [
        ([], 0.50, 0.0),  # empty -> 0.0, never a raise
        ([], 0.95, 0.0),
        ([3.0], 0.50, 3.0),  # single sample is every percentile
        ([3.0], 0.95, 3.0),
        ([1.0, 2.0], 0.50, 1.0),  # nearest-rank: p50 of two is the lower
        ([2.0, 1.0], 0.50, 1.0),  # unsorted input handled
        ([1.0, 2.0, 3.0, 4.0], 1.0, 4.0),  # p=1.0 is the max
        ([1.0, 2.0, 3.0, 4.0, 5.0], 0.95, 5.0),
    ],
)
def test_percentile_edge_cases(samples, p, expected):
    assert percentile(samples, p) == expected


def test_within_budget_boundary_inclusive():
    # Exactly-at-budget samples PASS: the contract is <=, not < (pins the comparison).
    rec = LatencyRecorder()
    for _ in range(5):
        rec.record(P50_BUDGET_S)
    assert rec.p50 == P50_BUDGET_S
    assert rec.within_budget() is True

    rec2 = LatencyRecorder()
    for _ in range(4):
        rec2.record(1.0)
    rec2.record(P95_BUDGET_S)  # p95 lands exactly on the budget
    assert rec2.p95 == P95_BUDGET_S
    assert rec2.within_budget() is True
