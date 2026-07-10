"""``app.obs`` structured event logging (2026-07-09-observability-tracing)."""

from __future__ import annotations

import logging

import pytest

import app.obs as obs_module
from app.obs import bind_call_context, bound_context, log_event


@pytest.fixture(autouse=True)
def _reset_call_context():
    obs_module._call_context.set(None)
    yield
    obs_module._call_context.set(None)


def test_log_event_basic_format(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "twilio.stt", ms=412.3, chars=7)
    assert "event=twilio.stt" in caplog.text
    assert "ms=412.3" in caplog.text
    assert "chars=7" in caplog.text


def test_log_event_attaches_bound_context(caplog):
    bind_call_context(session_id="sess-1", call_sid="CA123", turn_index=2)
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "twilio.turn.processed", ok=True)
    assert "session=sess-1" in caplog.text
    assert "call=CA123" in caplog.text
    assert "turn=2" in caplog.text
    assert "ok=true" in caplog.text


def test_explicit_field_wins_over_bound_context(caplog):
    bind_call_context(session_id="sess-1")
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", session="explicit")
    assert "session=explicit" in caplog.text
    assert "session=sess-1" not in caplog.text


def test_none_fields_are_omitted(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", missing=None, present=1)
    assert "missing=" not in caplog.text
    assert "present=1" in caplog.text


def test_values_with_spaces_are_quoted(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", note="hello world")
    assert 'note="hello world"' in caplog.text


def test_log_event_never_raises_on_bad_field(caplog):
    class Unformattable:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", bad=Unformattable())
    assert "event=x" in caplog.text


def test_bind_call_context_updates_incrementally():
    bind_call_context(session_id="s1")
    bind_call_context(call_sid="CA1")
    ctx = bound_context()
    assert ctx.session_id == "s1"
    assert ctx.call_sid == "CA1"


def test_bound_context_is_none_before_any_bind():
    assert bound_context() is None


def test_log_event_without_context_emits_no_correlation_ids(caplog):
    # No call context bound (obs "backend" absent from this scope): the line still
    # emits cleanly, just without session/call/turn fields.
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "twilio.start", ms=1.0)
    text = caplog.text
    assert "event=twilio.start" in text
    assert "session=" not in text
    assert "call=" not in text
    assert "turn=" not in text


def test_float_fields_are_formatted_to_one_decimal(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", ms=412.34567)
    assert "ms=412.3" in caplog.text


def test_bool_fields_are_lowercased(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", ok=True, bad=False)
    assert "ok=true" in caplog.text
    assert "bad=false" in caplog.text


def test_values_with_equals_sign_are_quoted(caplog):
    # An unquoted '=' inside a value would break the key=value grammar for downstream
    # `grep`/parsing — it must be quoted.
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", q="a=b")
    assert 'q="a=b"' in caplog.text


def test_embedded_double_quotes_are_downgraded_to_single(caplog):
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x", note='he said "hi"')
    assert "he said 'hi'" in caplog.text


def test_turn_index_zero_is_still_emitted(caplog):
    # turn=0 is a real, meaningful value — the guard is `is not None`, not truthiness.
    bind_call_context(session_id="s1", turn_index=0)
    with caplog.at_level(logging.INFO, logger="test.obs"):
        log_event(logging.getLogger("test.obs"), "x")
    assert "turn=0" in caplog.text


def test_bind_call_context_stores_extra_fields():
    ctx = bind_call_context(session_id="s1", provider="deepseek")
    assert ctx.extra["provider"] == "deepseek"
