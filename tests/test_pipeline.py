"""Sentence-chunker unit tests (requirements.md Decision 2)."""

from __future__ import annotations

from app.agent.pipeline import (
    FIRST_CLAUSE_MIN_CHARS,
    flush_remainder,
    split_ready_sentences,
)


def test_no_boundary_yet_returns_no_sentences() -> None:
    sentences, remainder = split_ready_sentences("Let me check that")
    assert sentences == []
    assert remainder == "Let me check that"


def test_one_complete_sentence_is_emitted() -> None:
    sentences, remainder = split_ready_sentences("Okay, got it. Now tell me")
    assert sentences == ["Okay, got it."]
    assert remainder == "Now tell me"


def test_multiple_complete_sentences_are_emitted_in_order() -> None:
    sentences, remainder = split_ready_sentences("First one. Second one! Still typing")
    assert sentences == ["First one.", "Second one!"]
    assert remainder == "Still typing"


def test_flush_remainder_returns_leftover_as_final_sentence() -> None:
    assert flush_remainder("trailing text") == ["trailing text"]
    assert flush_remainder("   ") == []
    assert flush_remainder("") == []


def test_question_and_exclamation_are_sentence_boundaries() -> None:
    sentences, remainder = split_ready_sentences("Is it plugged in? Try that. And then")
    assert sentences == ["Is it plugged in?", "Try that."]
    assert remainder == "And then"


def test_boundary_needs_trailing_whitespace_not_just_punctuation() -> None:
    # A period with no following whitespace (a decimal, an abbreviation mid-token, or
    # simply text still streaming) is not yet a boundary — it stays in the remainder.
    sentences, remainder = split_ready_sentences("The model is WF45.")
    assert sentences == []
    assert remainder == "The model is WF45."


def test_no_text_is_lost_across_a_split() -> None:
    buffer = "First. Second! Third? Still going"
    sentences, remainder = split_ready_sentences(buffer)
    # Reassembling the emitted sentences and the remainder recovers every word.
    assert " ".join(sentences + [remainder]) == buffer


# --- first_emission clause release (O6 / latency-engineering P1-3) ------------------


def _clause_string(min_first_clause: int) -> str:
    head = "Let me take a careful look at your washer for you"
    assert len(head) >= min_first_clause  # guard the fixture, not the code
    return head + ", and then we can go from there"


def test_first_emission_releases_opening_clause_past_the_floor() -> None:
    buffer = _clause_string(FIRST_CLAUSE_MIN_CHARS)
    sentences, remainder = split_ready_sentences(buffer, first_emission=True)
    assert sentences == ["Let me take a careful look at your washer for you,"]
    assert remainder == "and then we can go from there"


def test_clause_release_only_happens_on_the_first_emission() -> None:
    # The same buffer mid-reply (something already spoken) must NOT clause-split; a
    # clause boundary only earns an early release for the turn's very first audio.
    buffer = _clause_string(FIRST_CLAUSE_MIN_CHARS)
    sentences, remainder = split_ready_sentences(buffer, first_emission=False)
    assert sentences == []
    assert remainder == buffer


def test_short_first_clause_below_the_floor_does_not_release() -> None:
    # Comma present, but the opening clause is under FIRST_CLAUSE_MIN_CHARS — hold it.
    buffer = "Okay, one moment"
    assert len(buffer.split(",")[0]) < FIRST_CLAUSE_MIN_CHARS
    sentences, remainder = split_ready_sentences(buffer, first_emission=True)
    assert sentences == []
    assert remainder == buffer


def test_sentence_boundary_wins_over_clause_even_on_first_emission() -> None:
    # A real sentence boundary is always preferred over the clause escape hatch.
    buffer = "Your washer is on file. Now, about that grinding noise you mentioned"
    sentences, remainder = split_ready_sentences(buffer, first_emission=True)
    assert sentences == ["Your washer is on file."]
    assert remainder == "Now, about that grinding noise you mentioned"


def test_clause_release_loses_no_text() -> None:
    buffer = _clause_string(FIRST_CLAUSE_MIN_CHARS)
    sentences, remainder = split_ready_sentences(buffer, first_emission=True)
    # The stripped join differs only by the whitespace the split consumed.
    assert (sentences[0] + " " + remainder) == buffer
