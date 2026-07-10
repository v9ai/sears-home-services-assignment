"""Sentence-chunker unit tests (requirements.md Decision 2)."""

from __future__ import annotations

from app.agent.pipeline import flush_remainder, split_ready_sentences


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


def test_first_emission_clause_release_scans_past_an_early_comma() -> None:
    """f2 (loop-v2 i13): an early comma ("Got it,") must not defeat the clause
    release — the split scans to the FIRST boundary at/after the floor."""
    buf = "Got it, thanks for waiting just a moment, and one more thing"
    sentences, rest = split_ready_sentences(buf, first_emission=True)
    assert sentences == ["Got it, thanks for waiting just a moment,"]
    assert rest == "and one more thing"


def test_first_emission_floor_is_25_chars() -> None:
    """f2: a ~30-char opening clause releases (the old 40 floor held it back)."""
    buf = "Thanks for holding the line, let me pull that up"
    sentences, rest = split_ready_sentences(buf, first_emission=True)
    assert sentences == ["Thanks for holding the line,"]
    assert rest == "let me pull that up"
    # Below the floor: never clause-break.
    s2, r2 = split_ready_sentences("Well, ok", first_emission=True)
    assert s2 == [] and r2 == "Well, ok"
