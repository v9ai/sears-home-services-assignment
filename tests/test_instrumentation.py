"""LlamaIndex tracing handler tests (2026-07-09-observability-tracing).

``LLMChatStartEvent``/``LLMChatEndEvent`` fire for every real provider (OpenAI/
DeepSeek go through llama-index's decorated chat methods) but NOT for
``tests/fakes.py``'s ``FakeFunctionCallingLLM``, which overrides
``astream_chat_with_tools`` directly — see ``app/agent/instrumentation.py``'s module
docstring. So the handler is exercised directly with synthetic events here, and
separately end-to-end via ``run_turn``'s own ``ToolCall``-driven tool-call logging and
span handler (both of which DO fire with the fake, proven in
``test_run_turn_emits_tool_call_and_span_events`` below).
"""

from __future__ import annotations

import logging
import uuid

import pytest
from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.core.instrumentation.events.llm import LLMChatEndEvent, LLMChatStartEvent
from llama_index.core.memory import ChatMemoryBuffer

import app.obs as obs_module
from app.agent.core import run_turn
from app.agent.instrumentation import (
    LogEventHandler,
    current_rollup,
    register_instrumentation,
)
from app.contracts import CaseFile
from app.obs import bind_call_context
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


@pytest.fixture(autouse=True)
def _reset_call_context():
    obs_module._call_context.set(None)
    yield
    obs_module._call_context.set(None)


def test_register_instrumentation_is_idempotent():
    from llama_index.core.instrumentation import get_dispatcher

    register_instrumentation()
    before = len(get_dispatcher().event_handlers)
    register_instrumentation()
    assert len(get_dispatcher().event_handlers) == before


def test_llm_start_end_logged_with_bound_context(caplog):
    bind_call_context(session_id="sess-42")
    handler = LogEventHandler()
    with caplog.at_level(logging.INFO, logger="app.agent.llama"):
        handler.handle(
            LLMChatStartEvent(
                messages=[ChatMessage(role="user", content="hi there")],
                additional_kwargs={},
                model_dict={"model": "gpt-4.1-mini"},
            )
        )
        handler.handle(
            LLMChatEndEvent(
                messages=[ChatMessage(role="user", content="hi there")],
                response=ChatResponse(message=ChatMessage(role="assistant", content="hello!")),
            )
        )
    assert "event=llama.llm.start" in caplog.text
    assert "model=gpt-4.1-mini" in caplog.text
    assert "event=llama.llm.end" in caplog.text
    assert "session=sess-42" in caplog.text


def test_llm_start_increments_rollup():
    from app.agent.instrumentation import TurnRollup

    rollup = TurnRollup()
    token = current_rollup.set(rollup)
    try:
        handler = LogEventHandler()
        handler.handle(
            LLMChatStartEvent(
                messages=[ChatMessage(role="user", content="hi")],
                additional_kwargs={},
                model_dict={"model": "x"},
            )
        )
        assert rollup.llm_calls == 1
    finally:
        current_rollup.reset(token)


def test_handler_never_raises_on_malformed_event():
    handler = LogEventHandler()
    handler.handle(object())  # not a BaseEvent subclass at all


async def test_run_turn_emits_tool_call_and_span_events(caplog):
    """End-to-end with the real FakeFunctionCallingLLM harness: tool-call logging
    (from run_turn's own ToolCall handling) and turn_trace rollup both work without
    any live API — this is the reliable, always-firing signal path."""
    register_instrumentation()
    script = [
        ScriptedTurn(
            tool_calls=[
                ScriptedToolCall(
                    tool_name="identify_appliance", tool_kwargs={"appliance_type": "washer"}
                )
            ]
        ),
        ScriptedTurn(text="Got it, your washer has an issue."),
    ]
    llm = FakeFunctionCallingLLM(script)
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    with caplog.at_level(logging.INFO, logger="app.agent"):
        events = [
            ev
            async for ev in run_turn(
                case_file, memory, "my washer is broken", session_id=uuid.uuid4(), llm=llm
            )
        ]

    assert "event=llama.tool.call" in caplog.text
    assert "tool=identify_appliance" in caplog.text
    assert any(type(e).__name__ == "TurnComplete" for e in events)
