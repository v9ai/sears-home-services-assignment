"""Pure-function tests for `app.agent.trace.TurnTrace` (latency-engineering Scope A).

No network/LLM/TTS involved -- these hand-build a `marks` dict and assert on the
resulting `to_record()` arithmetic, the harness's own "budget-table math" self-test.
"""

from __future__ import annotations

import logging

import pytest

from app.agent.trace import TurnTrace, log_turn_trace


def test_mark_idempotent_first_write_wins():
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=1.0)
    trace.mark("t0", ts=99.0)
    assert trace.marks["t0"] == 1.0


def test_phone_record_derives_all_named_fields():
    trace = TurnTrace(channel="phone", session_id="abc")
    trace.mark("t0", ts=0.0)
    trace.mark("stt_done", ts=0.5)
    trace.mark("first_token", ts=0.8)
    trace.mark("first_sentence_ready", ts=1.0)
    trace.mark("first_audio", ts=1.3)
    trace.mark("turn_done", ts=2.0)

    record = trace.to_record()
    assert record["channel"] == "phone"
    assert record["session_id"] == "abc"
    assert record["eos_to_stt_ms"] == pytest.approx(500.0)
    assert record["stt_to_agent_first_token_ms"] == pytest.approx(300.0)
    assert record["first_token_to_first_sentence_ms"] == pytest.approx(200.0)
    assert record["agent_first_token_to_first_audio_ms"] == pytest.approx(500.0)
    assert record["eos_to_first_audio_ms"] == pytest.approx(1300.0)
    assert record["turn_total_ms"] == pytest.approx(2000.0)


def test_web_record_derives_submit_fields():
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=0.0)
    trace.mark("first_token", ts=0.4)
    trace.mark("first_audio", ts=0.9)
    trace.mark("turn_done", ts=1.5)

    record = trace.to_record()
    assert record["submit_to_first_token_ms"] == pytest.approx(400.0)
    assert record["submit_to_first_audio_ms"] == pytest.approx(900.0)
    assert record["turn_total_ms"] == pytest.approx(1500.0)
    assert "eos_to_stt_ms" not in record


def test_missing_marks_yield_none_not_zero_or_exception():
    trace = TurnTrace(channel="phone")
    record = trace.to_record()
    assert record["eos_to_stt_ms"] is None
    assert record["eos_to_first_audio_ms"] is None
    assert record["turn_total_ms"] is None


def test_web_record_omits_phone_only_fields():
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=0.0)
    trace.mark("first_audio", ts=0.5)
    record = trace.to_record()
    for phone_only in (
        "eos_to_stt_ms",
        "stt_to_agent_first_token_ms",
        "agent_first_token_to_first_audio_ms",
        "eos_to_first_audio_ms",
    ):
        assert phone_only not in record


def test_phone_record_omits_web_only_fields():
    trace = TurnTrace(channel="phone")
    trace.mark("t0", ts=0.0)
    trace.mark("first_token", ts=0.5)
    record = trace.to_record()
    assert "submit_to_first_token_ms" not in record
    assert "submit_to_first_audio_ms" not in record


def test_scenario_id_and_turn_index_pass_through_to_record():
    trace = TurnTrace(channel="web", scenario_id="t7_scheduling", turn_index=3)
    record = trace.to_record()
    assert record["scenario_id"] == "t7_scheduling"
    assert record["turn_index"] == 3


def test_extras_are_merged_into_the_record():
    # run_turn folds the per-turn rollup (llm_calls/tool_calls/tool_ms/...) in via
    # `extras`; to_record() must surface those fields verbatim alongside the timings.
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=0.0)
    trace.mark("turn_done", ts=1.0)
    trace.extras.update({"tool_calls": 2, "tool_names": "a,b", "tool_ms_total": 12.5})
    record = trace.to_record()
    assert record["tool_calls"] == 2
    assert record["tool_names"] == "a,b"
    assert record["tool_ms_total"] == 12.5
    assert record["turn_total_ms"] == pytest.approx(1000.0)


def test_to_record_is_pure_and_repeatable():
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=0.0)
    trace.mark("first_token", ts=0.3)
    first = trace.to_record()
    second = trace.to_record()
    assert first == second


def test_session_id_uuid_is_stringified():
    import uuid

    sid = uuid.uuid4()
    trace = TurnTrace(channel="phone", session_id=sid)
    record = trace.to_record()
    assert record["session_id"] == str(sid)
    assert isinstance(record["session_id"], str)


def test_partial_marks_leave_only_the_incomplete_delta_none():
    # first_token set but first_sentence_ready missing → that one delta is None while
    # a fully-marked delta still computes.
    trace = TurnTrace(channel="web")
    trace.mark("t0", ts=0.0)
    trace.mark("first_token", ts=0.4)
    record = trace.to_record()
    assert record["submit_to_first_token_ms"] == pytest.approx(400.0)
    assert record["first_token_to_first_sentence_ms"] is None


def test_log_turn_trace_emits_one_info_line(caplog):
    trace = TurnTrace(channel="web", session_id="sess-1")
    trace.mark("t0", ts=0.0)
    trace.mark("turn_done", ts=1.0)
    logger = logging.getLogger("test.trace")
    with caplog.at_level(logging.INFO, logger="test.trace"):
        log_turn_trace(trace, logger)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "turn_trace" in message
    assert "channel=web" in message
    assert "session=sess-1" in message
