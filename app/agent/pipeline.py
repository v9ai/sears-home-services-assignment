"""Sentence chunker over the agent's token stream (requirements.md Decision 2).

Splits a growing text buffer into complete sentences as soon as a sentence boundary is
seen, so each sentence can be handed to TTS concurrently with the next sentence still
generating — this is what keeps first-audio latency low instead of waiting for the
whole reply.
"""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_BOUNDARY = re.compile(r"(?<=[,;:])\s+")

# O6 (latency-engineering P1-3): a turn's FIRST emission may break at a clause
# boundary once at least this many chars have streamed — first audio starts on the
# opening clause instead of waiting for sentence punctuation.
FIRST_CLAUSE_MIN_CHARS = 40


def split_ready_sentences(buffer: str, *, first_emission: bool = False) -> tuple[list[str], str]:
    """Split off complete sentences from ``buffer``, returning ``(sentences, remainder)``.

    The last chunk after the final boundary is always treated as still-in-progress
    (it's kept in ``remainder``) since more text may still arrive for it.

    With ``first_emission=True`` (nothing spoken yet this turn), a clause boundary
    (comma/semicolon/colon) after ``FIRST_CLAUSE_MIN_CHARS`` chars also releases the
    opening clause — no text is ever lost; the remainder keeps accumulating.
    """
    parts = _SENTENCE_BOUNDARY.split(buffer)
    if len(parts) > 1:
        *complete, remainder = parts
        return [p.strip() for p in complete if p.strip()], remainder
    if first_emission and len(buffer) >= FIRST_CLAUSE_MIN_CHARS:
        clause_parts = _CLAUSE_BOUNDARY.split(buffer, maxsplit=1)
        if len(clause_parts) == 2 and len(clause_parts[0].strip()) >= FIRST_CLAUSE_MIN_CHARS:
            return [clause_parts[0].strip()], clause_parts[1]
    return [], buffer


def flush_remainder(buffer: str) -> list[str]:
    """At end-of-stream, treat whatever's left in the buffer as a final sentence."""
    text = buffer.strip()
    return [text] if text else []
