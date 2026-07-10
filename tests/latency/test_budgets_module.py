"""Pins and invariants for the central budget module (`app/latency/budgets.py`).

`test_budget_values_pinned` is the single intentional-change tripwire for every
latency budget in the repo — a number change fails HERE (and in the spec-sync test)
first, forcing the module + `specs/latency/budgets.md` to move together.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.latency import budgets


def test_budget_values_pinned():
    assert budgets.ALL_BUDGETS_MS == {
        "eos_to_stt_ms": 900,
        "stt_to_first_token_ms": 1200,
        "first_token_to_first_sentence_ms": 800,
        "tts_first_byte_ms": 500,
        "first_outbound_frame_ms": 100,
        "submit_to_first_token_ms": 1000,
        "phone_e2e_p50_ms": 2500,
        "phone_e2e_p95_ms": 4000,
        "web_e2e_p50_ms": 2000,
        "web_e2e_p95_ms": 3500,
        "phone_meaningful_p50_ms": 3200,
        "phone_meaningful_p95_ms": 5100,
        "web_meaningful_p50_ms": 2800,
        "web_meaningful_p95_ms": 4900,
        "answer_to_greeting_ms": 1500,
        "answer_to_greeting_cached_ms": 500,
        "filler_after_eos_ms": 800,
    }


def test_stage_budget_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        budgets.EOS_TO_STT.budget_ms = 1  # type: ignore[misc]


def test_e2e_budget_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        budgets.PHONE_E2E.p50_ms = 1  # type: ignore[misc]


def test_e2e_seconds_properties():
    assert budgets.PHONE_E2E.p50_s == 2.5
    assert budgets.PHONE_E2E.p95_s == 4.0
    assert budgets.WEB_E2E.p50_s == 2.0
    assert budgets.WEB_E2E.p95_s == 3.5


def test_micro_budgets_derived_from_stage_constants():
    assert budgets.MICRO_BUDGETS_MS == {
        "eos_to_stt_ms": budgets.EOS_TO_STT.budget_ms,
        "llm_ttft_ms": budgets.STT_TO_FIRST_TOKEN.budget_ms,
        "tts_first_byte_ms": budgets.TTS_FIRST_BYTE.budget_ms,
    }


def test_web_stricter_than_phone():
    # Web skips the L1-L3 telephony stages, so its envelope must stay strictly tighter —
    # guards an accidental channel swap in the module.
    assert budgets.WEB_E2E.p50_ms < budgets.PHONE_E2E.p50_ms
    assert budgets.WEB_E2E.p95_ms < budgets.PHONE_E2E.p95_ms


def test_all_budgets_positive():
    assert all(v > 0 for v in budgets.ALL_BUDGETS_MS.values())


def test_stage_names_match_all_budgets_keys():
    for stage in (
        budgets.EOS_TO_STT,
        budgets.STT_TO_FIRST_TOKEN,
        budgets.FIRST_TOKEN_TO_FIRST_SENTENCE,
        budgets.TTS_FIRST_BYTE,
        budgets.FIRST_OUTBOUND_FRAME,
        budgets.WEB_FIRST_TOKEN,
    ):
        assert budgets.ALL_BUDGETS_MS[stage.name] == stage.budget_ms


def test_vad_tunables_sane():
    assert 0 < budgets.VAD_STOP_SECS_MIN_SAFE <= budgets.VAD_STOP_SECS_DEFAULT
