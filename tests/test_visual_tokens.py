"""Token generation/expiry — visual-diagnosis (owned test file, no shared conftest edits)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.uploads import tokens


def test_generate_token_is_url_safe_and_unique():
    a, b = tokens.generate_token(), tokens.generate_token()
    assert a != b
    assert all(c.isalnum() or c in "-_" for c in a)
    assert len(a) >= 16


def test_new_expiry_is_24h_out():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    expiry = tokens.new_expiry(now)
    assert expiry - now == timedelta(hours=24)


def test_is_expired_true_after_ttl():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    expiry = tokens.new_expiry(now)
    assert not tokens.is_expired(expiry, now)
    assert not tokens.is_expired(expiry, now + timedelta(hours=23))
    assert tokens.is_expired(expiry, now + timedelta(hours=24))
    assert tokens.is_expired(expiry, now + timedelta(hours=25))


def test_is_expired_handles_naive_datetimes():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    naive_expiry = datetime(2026, 7, 8, 11, 0)  # no tzinfo
    assert tokens.is_expired(naive_expiry, now)


def test_generate_token_is_unique_across_a_large_batch():
    """~128 bits of entropy — collisions across a batch this size are effectively
    impossible, so a duplicate here means the generator regressed to a non-random source."""
    batch = {tokens.generate_token() for _ in range(2000)}
    assert len(batch) == 2000


def test_is_expired_is_inclusive_at_the_exact_expiry_instant():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    expiry = tokens.new_expiry(now)
    # A token is treated as expired the instant it reaches expires_at, not a tick later.
    assert tokens.is_expired(expiry, expiry)
    just_before = expiry - timedelta(microseconds=1)
    assert not tokens.is_expired(expiry, just_before)


def test_is_expired_defaults_now_to_current_time():
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    assert tokens.is_expired(past)  # no explicit now → compares against now()
    assert not tokens.is_expired(future)
