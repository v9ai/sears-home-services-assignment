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
# opening clause instead of waiting for sentence punctuation. Floor lowered 40 → 25
# by loop-v2 i13/f2 (~4 tokens ≈ earlier first-audio on clause-opening replies);
# clause release also now scans PAST an early comma ("Got it, thanks for waiting,")
# to the first boundary at/after the floor instead of giving up when the first
# clause alone is short. Choppiness guard: the hermetic eval rubrics must stay green.
FIRST_CLAUSE_MIN_CHARS = 25


def split_ready_sentences(buffer: str, *, first_emission: bool = False) -> tuple[list[str], str]:
    """Split off complete sentences from ``buffer``, returning ``(sentences, remainder)``.

    The last chunk after the final boundary is always treated as still-in-progress
    (it's kept in ``remainder``) since more text may still arrive for it.

    With ``first_emission=True`` (nothing spoken yet this turn), the first clause
    boundary (comma/semicolon/colon) at or beyond ``FIRST_CLAUSE_MIN_CHARS`` also
    releases the opening clause(s) — no text is ever lost; the remainder keeps
    accumulating.
    """
    parts = _SENTENCE_BOUNDARY.split(buffer)
    if len(parts) > 1:
        *complete, remainder = parts
        return [p.strip() for p in complete if p.strip()], remainder
    if first_emission and len(buffer) >= FIRST_CLAUSE_MIN_CHARS:
        for match in _CLAUSE_BOUNDARY.finditer(buffer):
            if match.start() >= FIRST_CLAUSE_MIN_CHARS:
                head = buffer[: match.start()].strip()
                if head:
                    return [head], buffer[match.end() :]
                break
    return [], buffer


def flush_remainder(buffer: str) -> list[str]:
    """At end-of-stream, treat whatever's left in the buffer as a final sentence."""
    text = buffer.strip()
    return [text] if text else []
