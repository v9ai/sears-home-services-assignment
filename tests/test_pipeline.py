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
