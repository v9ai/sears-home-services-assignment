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
