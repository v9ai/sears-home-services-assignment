"""Coverage for ``parse_window`` — the free-text availability-hint parser.

Pure Python (no DB): ``parse_window`` maps a caller phrase like "Tuesday
afternoon" onto a ``[start, end)`` datetime pair used as a *soft* slot filter.
All cases pin ``now`` to Wednesday 2026-07-08 12:00 UTC so weekday math and the
"same weekday means next week" rollover are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.matching import parse_window

WEDNESDAY_NOON = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)  # weekday() == 2


def test_unrecognized_and_empty_inputs_are_unfiltered():
    assert parse_window(None, now=WEDNESDAY_NOON) == (None, None)
    assert parse_window("", now=WEDNESDAY_NOON) == (None, None)
    assert parse_window("whenever is fine", now=WEDNESDAY_NOON) == (None, None)


def test_next_week_without_a_weekday_or_daypart_is_unfiltered():
    """ "next week" carries no weekday name and no day part, so the parser has no
    concrete window to anchor and returns the unfiltered sentinel (documents the
    soft-filter fallback rather than guessing a 7-day span)."""
    assert parse_window("sometime next week", now=WEDNESDAY_NOON) == (None, None)


def test_bare_daypart_uses_today():
    start, end = parse_window("afternoon", now=WEDNESDAY_NOON)
    assert (start, end) != (None, None)
    assert start.date() == WEDNESDAY_NOON.date()
    assert start.hour == 12
    assert end.hour == 17


def test_morning_afternoon_evening_hour_ranges():
    for phrase, (lo, hi) in {
        "tomorrow morning": (6, 12),
        "tomorrow afternoon": (12, 17),
        "tomorrow evening": (17, 21),
    }.items():
        start, end = parse_window(phrase, now=WEDNESDAY_NOON)
        assert start.hour == lo, phrase
        assert end.hour == hi, phrase


def test_tomorrow_alone_spans_the_whole_next_day():
    start, end = parse_window("tomorrow", now=WEDNESDAY_NOON)
    assert start == datetime(2026, 7, 9, 0, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


def test_bare_weekday_spans_the_whole_target_day():
    start, end = parse_window("monday", now=WEDNESDAY_NOON)
    assert start.weekday() == 0  # Monday
    assert start == datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


def test_same_weekday_rolls_over_to_next_week():
    """Saying "Wednesday" on a Wednesday means *next* Wednesday, not today —
    the parser must never resolve to a same-day zero-length or past window."""
    start, _ = parse_window("wednesday", now=WEDNESDAY_NOON)
    assert start.weekday() == 2
    assert start == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert (start - WEDNESDAY_NOON).days == 6  # 7 whole days from midnight-of-now


def test_weekday_and_daypart_combine():
    start, end = parse_window("Friday afternoon", now=WEDNESDAY_NOON)
    assert start.weekday() == 4  # Friday
    assert start.date() == datetime(2026, 7, 10, tzinfo=UTC).date()
    assert start.hour == 12
    assert end.hour == 17


def test_parsing_is_case_insensitive():
    lower = parse_window("friday evening", now=WEDNESDAY_NOON)
    upper = parse_window("FRIDAY EVENING", now=WEDNESDAY_NOON)
    assert lower == upper
    assert lower[0].hour == 17
    assert lower[1].hour == 21


def test_window_is_a_half_open_interval_with_positive_span():
    for phrase in ("tomorrow morning", "monday", "tuesday evening", "afternoon"):
        start, end = parse_window(phrase, now=WEDNESDAY_NOON)
        assert start < end, phrase
