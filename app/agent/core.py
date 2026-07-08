"""The real agent loop: a single LlamaIndex `FunctionAgent` run via `AgentWorkflow`
(requirements.md Decision 1), rebuilt fresh every turn so the case-file-derived system
prompt is always current (Decision 4) while the conversation `ChatMemoryBuffer` and the
`CaseFile` persist across turns at the call-site (`app/ws/routes.py`).
"""

from __future__ import annotations

import logging
import os
import time
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
from app.agent.state import current_case_file
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
    model = os.environ.get("OPENAI_LLM_MODEL", "gpt-4o")
    return OpenAI(model=model)


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
    llm: LLM | None = None,
) -> AsyncIterator[TurnEvent]:
    """Run one conversational turn, streaming sentences as they're ready.

    Tools mutate ``case_file`` in place via the ``current_case_file`` contextvar for
    the duration of this turn only.
    """
    workflow = build_agent(case_file, llm=llm)
    token = current_case_file.set(case_file)
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
        current_case_file.reset(token)
