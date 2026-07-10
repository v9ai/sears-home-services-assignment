"""Instrumentation branch coverage (bugfix-loop T12).

Five `LogEventHandler` branches (TTFT, usage extraction, embeddings,
exceptions), the `_MAX_TRACKED` eviction, and the span handler's
filter/error paths were unasserted. Writing them exposed a real defect:
dict-shaped `raw["usage"]` (DeepSeek-style raw payloads) was read with
`getattr`, silently logging no token counts — fixed alongside.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.core.instrumentation.events.embedding import (
    EmbeddingEndEvent,
    EmbeddingStartEvent,
)
from llama_index.core.instrumentation.events.exception import ExceptionEvent
from llama_index.core.instrumentation.events.llm import (
    LLMChatEndEvent,
    LLMChatInProgressEvent,
    LLMChatStartEvent,
)

import app.agent.instrumentation as instr
from app.agent.instrumentation import LogEventHandler, LogSpanHandler, TurnRollup, current_rollup

LOGGER = "app.agent.llama"


@pytest.fixture(autouse=True)
def _clean_tracking():
    instr._llm_starts.clear()
    instr._llm_ttft_seen.clear()
    yield
    instr._llm_starts.clear()
    instr._llm_ttft_seen.clear()


def _start(span_id: str = "span-1") -> LLMChatStartEvent:
    return LLMChatStartEvent(
        messages=[ChatMessage(role="user", content="hi")],
        additional_kwargs={},
        model_dict={"model": "gpt-4.1-mini"},
        span_id=span_id,
    )


def _end(span_id: str = "span-1", raw=None) -> LLMChatEndEvent:
    return LLMChatEndEvent(
        messages=[ChatMessage(role="user", content="hi")],
        response=ChatResponse(message=ChatMessage(role="assistant", content="hello!"), raw=raw),
        span_id=span_id,
    )


def test_ttft_logged_once_per_span(caplog) -> None:
    handler = LogEventHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.handle(_start())
        handler.handle(
            LLMChatInProgressEvent(
                messages=[ChatMessage(role="user", content="hi")],
                response=ChatResponse(message=ChatMessage(role="assistant", content="h")),
                span_id="span-1",
            )
        )
        handler.handle(
            LLMChatInProgressEvent(
                messages=[ChatMessage(role="user", content="hi")],
                response=ChatResponse(message=ChatMessage(role="assistant", content="he")),
                span_id="span-1",
            )
        )
    assert caplog.text.count("event=llama.llm.ttft") == 1


def test_usage_extracted_from_object_style_raw(caplog) -> None:
    handler = LogEventHandler()
    raw = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.handle(_start())
        handler.handle(_end(raw=raw))
    assert "prompt_tokens=11" in caplog.text
    assert "completion_tokens=7" in caplog.text


def test_usage_extracted_from_dict_style_raw(caplog) -> None:
    # DeepSeek-style raw payloads are plain dicts; getattr() on them silently
    # dropped the counts before the T12 fix.
    handler = LogEventHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.handle(_start())
        handler.handle(_end(raw={"usage": {"prompt_tokens": 13, "completion_tokens": 9}}))
    assert "prompt_tokens=13" in caplog.text
    assert "completion_tokens=9" in caplog.text


def test_end_event_accumulates_output_chars_on_the_rollup() -> None:
    handler = LogEventHandler()
    rollup = TurnRollup()
    token = current_rollup.set(rollup)
    try:
        handler.handle(_start())
        handler.handle(_end())
    finally:
        current_rollup.reset(token)
    assert rollup.llm_calls == 1
    assert rollup.output_chars == len("hello!")


def test_exception_event_logs_error_type(caplog) -> None:
    handler = LogEventHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.handle(ExceptionEvent(exception=ValueError("boom")))
    assert "event=llama.exception" in caplog.text
    assert "error_type=ValueError" in caplog.text


def test_embedding_events_log_start_and_count(caplog) -> None:
    handler = LogEventHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.handle(EmbeddingStartEvent(model_dict={}))
        handler.handle(EmbeddingEndEvent(chunks=["a", "b", "c"], embeddings=[[0.1], [0.2], [0.3]]))
    assert "event=llama.embedding.start" in caplog.text
    assert "n_texts=3" in caplog.text


def test_tracking_dicts_evict_past_max_tracked() -> None:
    handler = LogEventHandler()
    for i in range(instr._MAX_TRACKED + 1):
        instr._llm_starts[f"stale-{i}"] = 0.0
        instr._llm_ttft_seen.add(f"stale-{i}")
    handler.handle(_start(span_id="fresh"))
    assert "fresh" in instr._llm_starts
    assert len(instr._llm_starts) == 1, "eviction must clear the stale entries"
    assert not any(k.startswith("stale-") for k in instr._llm_ttft_seen)


def test_span_exit_logs_only_signal_qualnames(caplog) -> None:
    handler = LogSpanHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.span_enter(id_="AgentWorkflow.run-abc", bound_args=None)
        handler.prepare_to_exit_span(id_="AgentWorkflow.run-abc", bound_args=None)
        handler.span_enter(id_="SomeHelper._fmt-xyz", bound_args=None)
        handler.prepare_to_exit_span(id_="SomeHelper._fmt-xyz", bound_args=None)
    assert "event=llama.span " in caplog.text
    assert "span=AgentWorkflow.run" in caplog.text
    assert "SomeHelper" not in caplog.text


def test_span_drop_with_error_logs_span_error(caplog) -> None:
    handler = LogSpanHandler()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        handler.span_enter(id_="ToolCall.run-1", bound_args=None)
        handler.prepare_to_drop_span(
            id_="ToolCall.run-1", bound_args=None, err=RuntimeError("died")
        )
    assert "event=llama.span.error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
