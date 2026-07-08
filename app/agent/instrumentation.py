"""LlamaIndex full tracing → structured logs (2026-07-09-observability-tracing).

Registers handlers on llama-index's own instrumentation dispatcher — the library's
native seam (`llama_index.core.instrumentation`) — so every LLM call, streamed first
token, tool invocation, embedding batch, and internal span is one grep-able
``event=llama.*`` line, correlated to the call via ``app.obs`` context binding. No
third-party APM: the handler boundary keeps a future OTel exporter drop-in.

Per-turn rollups (llm_calls / tool_calls / tool_names / output_chars) accumulate on a
contextvar that ``run_turn`` opens and folds into its ``turn_trace`` line, so one line
summarizes each turn's full anatomy.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from llama_index.core.instrumentation import get_dispatcher
from llama_index.core.instrumentation.event_handlers import BaseEventHandler
from llama_index.core.instrumentation.events import BaseEvent
from llama_index.core.instrumentation.events.agent import AgentToolCallEvent
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
from llama_index.core.instrumentation.span import SimpleSpan
from llama_index.core.instrumentation.span_handlers import BaseSpanHandler

from app.obs import bound_context, log_event

logger = logging.getLogger("app.agent.llama")

TRACE_DUMP_DIR = os.environ.get("TRACE_DUMP_DIR", "")


@dataclass
class TurnRollup:
    """Per-turn counters folded into the turn_trace line by run_turn."""

    llm_calls: int = 0
    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    output_chars: int = 0

    def as_fields(self) -> dict[str, object]:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tool_names": ",".join(self.tool_names) or None,
            "output_chars": self.output_chars,
        }


current_rollup: ContextVar[TurnRollup | None] = ContextVar("llama_turn_rollup", default=None)

# span_id -> start info, kept small; llm TTFT is stamped once per span.
_llm_starts: dict[str, float] = {}
_llm_ttft_seen: set[str] = set()
_MAX_TRACKED = 256


def _dump(event_name: str, payload: dict[str, Any]) -> None:
    if not TRACE_DUMP_DIR:
        return
    try:
        ctx = bound_context()
        session = (ctx.session_id if ctx else None) or "unbound"
        os.makedirs(TRACE_DUMP_DIR, exist_ok=True)
        with open(os.path.join(TRACE_DUMP_DIR, f"{session}.jsonl"), "a") as fh:
            fh.write(json.dumps({"ts": time.time(), "event": event_name, **payload}) + "\n")
    except Exception:  # pragma: no cover — best-effort by contract
        pass


class LogEventHandler(BaseEventHandler):
    """Every dispatcher event → one structured log line. Never raises."""

    @classmethod
    def class_name(cls) -> str:
        return "SHSLogEventHandler"

    def handle(self, event: BaseEvent, **kwargs: Any) -> None:
        try:
            self._handle(event)
        except Exception:  # pragma: no cover — never break the turn for a log line
            logger.debug("instrumentation_handler_failed", exc_info=True)

    def _handle(self, event: BaseEvent) -> None:
        rollup = current_rollup.get()
        if isinstance(event, LLMChatStartEvent):
            if len(_llm_starts) > _MAX_TRACKED:
                _llm_starts.clear()
                _llm_ttft_seen.clear()
            _llm_starts[event.span_id or event.id_] = time.monotonic()
            if rollup is not None:
                rollup.llm_calls += 1
            model = (event.model_dict or {}).get("model")
            input_chars = sum(len(str(m.content) or "") for m in event.messages)
            log_event(
                logger,
                "llama.llm.start",
                model=model,
                n_messages=len(event.messages),
                input_chars=input_chars,
            )
            _dump("llama.llm.start", {"model": model, "n_messages": len(event.messages)})
        elif isinstance(event, LLMChatInProgressEvent):
            key = event.span_id or event.id_
            if key in _llm_starts and key not in _llm_ttft_seen:
                _llm_ttft_seen.add(key)
                ms = (time.monotonic() - _llm_starts[key]) * 1000
                log_event(logger, "llama.llm.ttft", ms=ms)
                _dump("llama.llm.ttft", {"ms": ms})
        elif isinstance(event, LLMChatEndEvent):
            key = event.span_id or event.id_
            started = _llm_starts.pop(key, None)
            _llm_ttft_seen.discard(key)
            ms = (time.monotonic() - started) * 1000 if started is not None else None
            text = str(event.response.message.content or "") if event.response else ""
            if rollup is not None:
                rollup.output_chars += len(text)
            usage: dict[str, object] = {}
            raw = getattr(event.response, "raw", None) if event.response else None
            raw_usage = getattr(raw, "usage", None) or (
                raw.get("usage") if isinstance(raw, dict) else None
            )
            if raw_usage is not None:
                usage["prompt_tokens"] = getattr(raw_usage, "prompt_tokens", None)
                usage["completion_tokens"] = getattr(raw_usage, "completion_tokens", None)
            log_event(logger, "llama.llm.end", ms=ms, output_chars=len(text), **usage)
            _dump("llama.llm.end", {"ms": ms, "output_chars": len(text)})
        elif isinstance(event, AgentToolCallEvent):
            if rollup is not None:
                rollup.tool_calls += 1
                rollup.tool_names.append(event.tool.name)
            arg_keys = None
            try:
                arg_keys = ",".join(sorted(json.loads(event.arguments)))
            except Exception:
                pass
            log_event(logger, "llama.tool.call", tool=event.tool.name, arg_keys=arg_keys)
            _dump("llama.tool.call", {"tool": event.tool.name, "arguments": event.arguments})
        elif isinstance(event, EmbeddingStartEvent):
            log_event(logger, "llama.embedding.start")
        elif isinstance(event, EmbeddingEndEvent):
            log_event(logger, "llama.embedding", n_texts=len(event.chunks))
        elif isinstance(event, ExceptionEvent):
            log_event(logger, "llama.exception", error_type=type(event.exception).__name__)
            _dump("llama.exception", {"error_type": type(event.exception).__name__})


class LogSpanHandler(BaseSpanHandler[SimpleSpan]):
    """Span exits → ``event=llama.span`` with duration; the turn's request anatomy."""

    @classmethod
    def class_name(cls) -> str:
        return "SHSLogSpanHandler"

    def new_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Any | None = None,
        parent_span_id: str | None = None,
        tags: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> SimpleSpan | None:
        return SimpleSpan(id_=id_, parent_id=parent_span_id, tags=tags or {})

    def prepare_to_exit_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Any | None = None,
        result: Any | None = None,
        **kwargs: Any,
    ) -> SimpleSpan | None:
        span = self.open_spans.get(id_)
        if span is not None:
            try:
                duration = (time.time() - span.start_time.timestamp()) * 1000
                # keep the signal: agent/llm/tool spans only, not every helper call
                qualname = id_.split("-")[0]
                if any(k in qualname.lower() for k in ("agent", "llm", "tool", "workflow")):
                    log_event(logger, "llama.span", span=qualname, ms=duration)
            except Exception:  # pragma: no cover
                pass
        return span

    def prepare_to_drop_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Any | None = None,
        err: BaseException | None = None,
        **kwargs: Any,
    ) -> SimpleSpan | None:
        if err is not None:
            log_event(logger, "llama.span.error", span=id_.split("-")[0], error_type=type(err).__name__)
        return self.open_spans.get(id_)


_registered = False


def register_instrumentation() -> None:
    """Attach the log handlers to the root dispatcher exactly once."""
    global _registered
    if _registered:
        return
    dispatcher = get_dispatcher()
    dispatcher.add_event_handler(LogEventHandler())
    dispatcher.add_span_handler(LogSpanHandler())
    _registered = True
    logger.info("event=llama.instrumentation.registered")
