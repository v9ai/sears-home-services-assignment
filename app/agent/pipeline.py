"""Sentence chunker over the agent's token stream (requirements.md Decision 2).

Splits a growing text buffer into complete sentences as soon as a sentence boundary is
seen, so each sentence can be handed to TTS concurrently with the next sentence still
generating — this is what keeps first-audio latency low instead of waiting for the
whole reply.
"""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_ready_sentences(buffer: str) -> tuple[list[str], str]:
    """Split off complete sentences from ``buffer``, returning ``(sentences, remainder)``.

    The last chunk after the final boundary is always treated as still-in-progress
    (it's kept in ``remainder``) since more text may still arrive for it.
    """
    parts = _SENTENCE_BOUNDARY.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    *complete, remainder = parts
    return [p.strip() for p in complete if p.strip()], remainder


def flush_remainder(buffer: str) -> list[str]:
    """At end-of-stream, treat whatever's left in the buffer as a final sentence."""
    text = buffer.strip()
    return [text] if text else []
