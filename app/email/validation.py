"""Normalize caller-provided email addresses before they hit the DB or a send.

Voice capture means the address arrives via STT + the LLM, so it can carry spoken
forms ("d martinez99 at gmail dot com"), a ``mailto:`` prefix, stray spaces, or
trailing sentence punctuation. ``normalize_email`` repairs the recoverable cases
conservatively and returns ``None`` for anything that still isn't a plausible
address — callers treat ``None`` as "re-confirm with the caller", never send.
"""

from __future__ import annotations

import re

# Pragmatic shape check, not RFC 5322: one @, no spaces, a dotted domain.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SPOKEN_AT = re.compile(r"\s+at\s+", re.IGNORECASE)
_SPOKEN_DOT = re.compile(r"\s+dot\s+", re.IGNORECASE)


def normalize_email(raw: str | None) -> str | None:
    """Return a cleaned, lowercased address, or ``None`` if it can't be made valid."""
    if raw is None:
        return None
    email = raw.strip().lower()
    if email.startswith("mailto:"):
        email = email[len("mailto:") :]
    email = email.rstrip(".,;:!?")
    if "@" not in email:
        email = _SPOKEN_AT.sub("@", email)
    email = _SPOKEN_DOT.sub(".", email)
    email = email.replace(" ", "")
    if not _EMAIL_RE.fullmatch(email):
        return None
    return email
