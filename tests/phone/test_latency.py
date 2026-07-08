"""Latency instrumentation unit tests (plan.md group 5: end-of-speech -> first-audio,
budget p50 <= 2.5s / p95 <= 4s)."""

import logging

from app.phone.latency import P50_BUDGET_S, P95_BUDGET_S, LatencyRecorder


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
