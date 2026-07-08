"""Upload token generation and expiry.

Decision (requirements.md §Decisions #1): a 128-bit ``secrets.token_urlsafe`` stored in
the ``image_uploads`` row, not a JWT — revocable, single-use, no key management to
review. ``UPLOAD_TOKEN_SECRET`` stays reserved for a future signed-token scheme.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

TOKEN_TTL_HOURS = 24


def generate_token() -> str:
    """A URL-safe, single-use upload token (~128 bits of entropy)."""
    return secrets.token_urlsafe(16)


def new_expiry(now: datetime | None = None) -> datetime:
    """The expiry timestamp for a freshly created token."""
    base = now or datetime.now(UTC)
    return base + timedelta(hours=TOKEN_TTL_HOURS)


def is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return current >= expires_at
