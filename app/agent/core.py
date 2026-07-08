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
from llama_index.core.agent.workflow.workflow_events import AgentStream, ToolCall
from llama_index.core.llms.llm import LLM
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.llms.openai import OpenAI

from app.agent.pipeline import flush_remainder, split_ready_sentences
from app.agent.prompts import build_system_prompt
from app.agent.state import current_case_file, current_session_id
from app.contracts import CaseFile
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


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    """Agent LLM factory (tech-stack.md → Models; 2026-07-08-deepseek-agent-llm spec).

    Default: DeepSeek `deepseek-chat` called directly through LlamaIndex's
    function-calling `DeepSeek` class. `deepseek-reasoner` is not supported — it has no
    function calling, which the tool loop requires. `LLM_PROVIDER=openai` falls back to
    the previous `gpt-4o` path (demo-day resilience).
    """
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    if provider == "openai":
        return OpenAI(model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4o"))
    from llama_index.llms.deepseek import DeepSeek

    return DeepSeek(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
    )


def build_agent(case_file: CaseFile, llm: LLM | None = None) -> AgentWorkflow:
    """Construct a fresh single-agent workflow with a case-file-current system prompt."""
    agent = FunctionAgent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        system_prompt=build_system_prompt(case_file),
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
) -> AsyncIterator[TurnEvent]:
    """Run one conversational turn, streaming sentences as they're ready.

    Tools mutate ``case_file`` in place via the ``current_case_file`` contextvar for
    the duration of this turn only. ``session_id`` is threaded through the
    ``current_session_id`` contextvar so session-scoped tools (the visual-diagnosis
    upload tools) can attach their work to the caller's session; it's optional so the
    eval harness can drive a turn without a persisted session.
    """
    workflow = build_agent(case_file, llm=llm)
    token = current_case_file.set(case_file)
    session_token = current_session_id.set(session_id)
    turn_started = time.monotonic()
    first_token_logged = False
    try:
        handler = workflow.run(user_msg=user_text, memory=memory)
        buffer = ""
        emitted: list[str] = []
        async for event in handler.stream_events():
            if isinstance(event, ToolCall):
                yield ToolInvoked(tool_name=event.tool_name)
            elif isinstance(event, AgentStream) and event.delta:
                if not first_token_logged:
                    first_token_logged = True
                    logger.info(
                        "first_token_latency_ms=%.0f",
                        (time.monotonic() - turn_started) * 1000,
                    )
                buffer += event.delta
                sentences, buffer = split_ready_sentences(buffer)
                for sentence in sentences:
                    emitted.append(sentence)
                    yield SentenceReady(text=sentence)
        await handler
        for sentence in flush_remainder(buffer):
            emitted.append(sentence)
            yield SentenceReady(text=sentence)
        yield TurnComplete(full_text=" ".join(emitted))
    finally:
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
