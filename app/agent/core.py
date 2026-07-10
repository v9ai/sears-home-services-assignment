"""The real agent loop: a single LlamaIndex `FunctionAgent` run via `AgentWorkflow`
(requirements.md Decision 1), rebuilt fresh every turn so the case-file-derived system
prompt is always current (Decision 4) while the conversation `ChatMemoryBuffer` and the
`CaseFile` persist across turns at the call-site (`app/ws/routes.py`).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache

from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.agent.workflow.workflow_events import (
    AgentStream,
    ToolCall,
    ToolCallResult,
)
from llama_index.core.llms.llm import LLM
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.llms.openai import OpenAI

from app.agent.pipeline import flush_remainder, split_ready_sentences
from app.agent.prompts import build_system_prompt
from app.agent.state import current_case_file, current_session_id, get_offered_slots
from app.agent.trace import TurnTrace
from app.contracts import CaseFile
from app.obs import log_event
from app.tools.registry import get_tools

logger = logging.getLogger("app.agent")

AGENT_NAME = "sears_home_services_agent"
AGENT_DESCRIPTION = (
    "A Sears Home Services agent that diagnoses appliance issues, walks callers "
    "through safe troubleshooting, and schedules technicians when needed."
)


@dataclass(frozen=True)
class SentenceReady:
    """One complete sentence of the agent's reply, ready for TTS + transcript."""

    text: str


@dataclass(frozen=True)
class ToolInvoked:
    """A tool call started (used for the "let me check that" spoken filler)."""

    tool_name: str


@dataclass(frozen=True)
class TurnComplete:
    """The turn finished; ``full_text`` is every sentence emitted, joined."""

    full_text: str


TurnEvent = SentenceReady | ToolInvoked | TurnComplete


# The api_key on llama_index's OpenAI/DeepSeek LLM objects is a plain-string pydantic
# field: repr(), str(), model_dump() and model_dump_json() all echo the raw key. The app
# never logs the LLM object today, so there is no active leak — but a future
# `logger.info(llm)`, trace dump, or exception repr would expose it. These factory
# subclasses keep api_key a real string (the OpenAI client reads it lazily via
# _get_credential_kwargs, so real calls are untouched) while redacting it everywhere the
# object renders itself. A bare repr() never consults instance attributes, so the
# redaction has to live on the type — hence subclasses rather than an instance override.
_REDACTED_API_KEY = "***redacted***"


class _RedactsApiKey:
    """Mixin: redact ``api_key`` in every self-rendering path without disturbing the
    value the client actually uses."""

    def __repr_args__(self):  # drives BaseModel.__repr__ AND __str__
        return [
            (k, _REDACTED_API_KEY if k == "api_key" and v else v)
            for k, v in super().__repr_args__()
        ]

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if data.get("api_key"):
            data["api_key"] = _REDACTED_API_KEY
        return data

    def model_dump_json(self, **kwargs) -> str:
        # Reserialize from the redacted python dump so the key never reaches the JSON;
        # pydantic's own model_dump_json would serialize the raw field directly.
        import json

        indent = kwargs.get("indent")
        dump_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            in (
                "include",
                "exclude",
                "by_alias",
                "exclude_unset",
                "exclude_defaults",
                "exclude_none",
                "round_trip",
                "warnings",
            )
        }
        separators = None if indent else (",", ":")
        return json.dumps(
            self.model_dump(mode="json", **dump_kwargs), indent=indent, separators=separators
        )


class _RedactedOpenAI(_RedactsApiKey, OpenAI):
    pass


# Reported class name stays "OpenAI"/"DeepSeek" so isinstance and the factory's
# provider-identity contract (tests/test_llm_factory.py) are unchanged.
_RedactedOpenAI.__name__ = "OpenAI"
_RedactedOpenAI.__qualname__ = "OpenAI"


@lru_cache(maxsize=1)
def _redacted_deepseek_cls() -> type:
    from llama_index.llms.deepseek import DeepSeek

    cls = type("DeepSeek", (_RedactsApiKey, DeepSeek), {})
    cls.__qualname__ = "DeepSeek"
    return cls


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    """Agent LLM factory (tech-stack.md → Models; 2026-07-08-deepseek-agent-llm spec).

    Default: DeepSeek `deepseek-chat` called directly through LlamaIndex's
    function-calling `DeepSeek` class. `deepseek-reasoner` is not supported — it has no
    function calling, which the tool loop requires. `LLM_PROVIDER=openai` falls back to
    the previous `gpt-4o` path (demo-day resilience).
    """
    # Normalized like the voice factories (app/voice/bot.py) — LLM_PROVIDER="OpenAI" must not
    # silently fall through to DeepSeek here while the voice pipeline honors it.
    provider = os.environ.get("LLM_PROVIDER", "deepseek").strip().lower()
    if provider == "openai":
        return _RedactedOpenAI(model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4o"))

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    if model.startswith("deepseek-reasoner"):
        # Fail fast at build time instead of confusingly mid-turn: reasoner has no function
        # calling, which the tool loop requires (docstring above; .env.example:6).
        raise ValueError(
            "deepseek-reasoner is not supported: it has no function calling, "
            "which the tool loop requires. Use deepseek-chat."
        )
    return _redacted_deepseek_cls()(
        model=model,
        api_key=os.environ["DEEPSEEK_API_KEY"],
    )


def build_agent(
    case_file: CaseFile,
    llm: LLM | None = None,
    offered_slots: list[dict[str, str]] | None = None,
) -> AgentWorkflow:
    """Construct a fresh single-agent workflow with a case-file-current system prompt.

    ``offered_slots`` (task #21) are the scheduling slots last offered this session; they
    are surfaced in the system prompt so an accepted slot books without a re-search.
    """
    agent = FunctionAgent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        system_prompt=build_system_prompt(case_file, offered_slots),
        tools=get_tools(),
        llm=llm or get_llm(),
    )
    return AgentWorkflow(agents=[agent])


async def run_turn(
    case_file: CaseFile,
    memory: ChatMemoryBuffer,
    user_text: str,
    *,
    session_id: uuid.UUID | None = None,
    llm: LLM | None = None,
    trace: TurnTrace | None = None,
) -> AsyncIterator[TurnEvent]:
    """Run one conversational turn, streaming sentences as they're ready.

    Tools mutate ``case_file`` in place via the ``current_case_file`` contextvar for
    the duration of this turn only. ``session_id`` is threaded through the
    ``current_session_id`` contextvar so session-scoped tools (the visual-diagnosis
    upload tools) can attach their work to the caller's session; it's optional so the
    eval harness can drive a turn without a persisted session. ``trace`` is an optional
    latency-engineering ``TurnTrace``; when passed, ``first_token``/``first_sentence_ready``
    are stamped alongside the existing log-only timing.
    """
    from app.agent.instrumentation import TurnRollup, current_rollup

    # Surface any slots already offered this session (task #21) so an accepted slot books
    # without re-searching. Fetched by session id here rather than via the contextvar,
    # since current_session_id is set below (after the agent — and thus its prompt — is
    # built).
    workflow = build_agent(case_file, llm=llm, offered_slots=get_offered_slots(session_id))
    token = current_case_file.set(case_file)
    session_token = current_session_id.set(session_id)
    rollup = TurnRollup()
    rollup_token = current_rollup.set(rollup)
    turn_started = time.monotonic()
    first_token_logged = False
    first_sentence_logged = False
    try:
        handler = workflow.run(user_msg=user_text, memory=memory)
        buffer = ""
        emitted: list[str] = []
        # t1 (loop-v2): per-tool wall attribution — ToolCall/ToolCallResult event pairs
        # keyed by tool_id (parallel calls interleave; the id disambiguates).
        tool_started_at: dict[str, tuple[str, float]] = {}
        async for event in handler.stream_events():
            if isinstance(event, ToolCallResult):
                started = tool_started_at.pop(event.tool_id, None)
                if started is not None:
                    name, t_start = started
                    rollup.tool_timings_ms.append((name, (time.monotonic() - t_start) * 1000))
            elif isinstance(event, ToolCall):
                tool_started_at[event.tool_id] = (event.tool_name, time.monotonic())
                # P0-4 enforcement (latency-engineering): an LLM round that ends in tool
                # calls streams no further deltas, so any buffered pre-tool
                # acknowledgment ("Got it — one moment.", 21 chars) would sit under the
                # 40-char first-clause floor through EVERY tool round trip and only
                # reach the caller with the NEXT LLM response — flush it now instead.
                if buffer.strip():
                    for sentence in flush_remainder(buffer):
                        emitted.append(sentence)
                        if not first_sentence_logged:
                            first_sentence_logged = True
                            if trace is not None:
                                trace.mark("first_sentence_ready")
                        yield SentenceReady(text=sentence)
                    buffer = ""
                rollup.tool_calls += 1
                rollup.tool_names.append(event.tool_name)
                log_event(
                    logger,
                    "llama.tool.call",
                    tool=event.tool_name,
                    arg_keys=",".join(sorted(event.tool_kwargs)) or None,
                )
                yield ToolInvoked(tool_name=event.tool_name)
            elif isinstance(event, AgentStream) and event.delta:
                if not first_token_logged:
                    first_token_logged = True
                    if trace is not None:
                        trace.mark("first_token")
                    logger.info(
                        "first_token_latency_ms=%.0f",
                        (time.monotonic() - turn_started) * 1000,
                    )
                buffer += event.delta
                # O6: the first emission may release an opening clause early.
                sentences, buffer = split_ready_sentences(buffer, first_emission=not emitted)
                for sentence in sentences:
                    emitted.append(sentence)
                    if not first_sentence_logged:
                        first_sentence_logged = True
                        if trace is not None:
                            trace.mark("first_sentence_ready")
                    yield SentenceReady(text=sentence)
        await handler
        for sentence in flush_remainder(buffer):
            emitted.append(sentence)
            if not first_sentence_logged:
                first_sentence_logged = True
                if trace is not None:
                    trace.mark("first_sentence_ready")
            yield SentenceReady(text=sentence)
        if trace is not None:
            trace.mark("turn_done")
            trace.extras.update(rollup.as_fields())
        yield TurnComplete(full_text=" ".join(emitted))
    finally:
        current_rollup.reset(rollup_token)
        # These tokens must be reset in the context that created them. On normal
        # completion the finally runs in that same context and reset() restores the
        # prior value. But when the consumer disconnects mid-turn (a caller hanging up
        # is routine on the voice channel), the async generator is finalized from a
        # foreign context and reset() raises "Token was created in a different Context".
        # That context is being torn down, so there is nothing to restore — swallow it
        # rather than let it surface as an ASGI error that masks real failures.
        for var, tok in ((current_case_file, token), (current_session_id, session_token)):
            try:
                var.reset(tok)
            except ValueError:
                pass
