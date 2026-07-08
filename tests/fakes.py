"""A scripted `FunctionCallingLLM` test double.

`FunctionAgent` requires a real `FunctionCallingLLM` (it calls `astream_chat_with_tools`
and `get_tool_calls_from_response`), so a plain `MockLLM` can't stand in for it. This
fake lets `tests/test_agent_core.py` drive the *real* `AgentWorkflow` + tool-calling
loop end to end — proving the wiring works — without a live `OPENAI_API_KEY` or a
network call, per COORDINATION.md's "stub seams" spirit applied to this feature's own
critical-path harness.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    LLMMetadata,
)
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.llms.function_calling import FunctionCallingLLM
from llama_index.core.llms.llm import ToolSelection
from llama_index.core.tools.types import BaseTool


@dataclass
class ScriptedToolCall:
    tool_name: str
    tool_kwargs: dict
    tool_id: str = "call_0"


@dataclass
class ScriptedTurn:
    """One LLM "turn": either plain text, or one/more tool calls (never both, like OpenAI)."""

    text: str = ""
    tool_calls: list[ScriptedToolCall] = field(default_factory=list)


class FakeFunctionCallingLLM(FunctionCallingLLM):
    """Replays a fixed script of turns, one per `astream_chat_with_tools` call."""

    _script: list[ScriptedTurn] = PrivateAttr(default_factory=list)
    _call_index: int = PrivateAttr(default=0)

    def __init__(self, script: Sequence[ScriptedTurn], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._script = list(script)
        self._call_index = 0

    @classmethod
    def class_name(cls) -> str:
        return "FakeFunctionCallingLLM"

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(is_function_calling_model=True, model_name="fake-llm")

    def _next_turn(self) -> ScriptedTurn:
        turn = self._script[min(self._call_index, len(self._script) - 1)]
        self._call_index += 1
        return turn

    def get_tool_calls_from_response(
        self, response: ChatResponse, error_on_no_tool_call: bool = True, **kwargs: object
    ) -> list[ToolSelection]:
        return response.message.additional_kwargs.get("tool_calls", [])

    def _prepare_chat_with_tools(
        self,
        tools: Sequence[BaseTool],
        user_msg: str | ChatMessage | None = None,
        chat_history: list[ChatMessage] | None = None,
        verbose: bool = False,
        allow_parallel_tool_calls: bool = False,
        tool_required: bool = False,
        **kwargs: object,
    ) -> dict[str, object]:
        # Unused: this fake's astream_chat_with_tools is overridden directly and never
        # delegates through the default compat path that calls this method.
        return {"messages": chat_history or []}

    async def astream_chat_with_tools(
        self,
        tools: Sequence[BaseTool],
        user_msg: str | ChatMessage | None = None,
        chat_history: list[ChatMessage] | None = None,
        verbose: bool = False,
        allow_parallel_tool_calls: bool = False,
        tool_required: bool = False,
        **kwargs: object,
    ) -> ChatResponseAsyncGen:
        turn = self._next_turn()
        selections = [
            ToolSelection(tool_id=tc.tool_id, tool_name=tc.tool_name, tool_kwargs=tc.tool_kwargs)
            for tc in turn.tool_calls
        ]

        async def _gen() -> AsyncGenerator[ChatResponse, None]:
            text = turn.text
            if not text:
                message = ChatMessage(
                    role="assistant", content="", additional_kwargs={"tool_calls": selections}
                )
                yield ChatResponse(message=message, delta="")
                return
            accumulated = ""
            for char in text:
                accumulated += char
                message = ChatMessage(
                    role="assistant",
                    content=accumulated,
                    additional_kwargs={"tool_calls": selections},
                )
                yield ChatResponse(message=message, delta=char)

        return _gen()

    # --- Required abstract members of LLM / FunctionCallingLLM; unused by this suite. ---

    async def achat(self, messages: Sequence[ChatMessage], **kwargs: object) -> ChatResponse:
        raise NotImplementedError("FakeFunctionCallingLLM only supports streaming-with-tools.")

    async def astream_chat(self, messages: Sequence[ChatMessage], **kwargs: object):
        raise NotImplementedError("FakeFunctionCallingLLM only supports streaming-with-tools.")

    async def acomplete(self, prompt: str, **kwargs: object):
        raise NotImplementedError

    async def astream_complete(self, prompt: str, **kwargs: object):
        raise NotImplementedError

    def chat(self, messages: Sequence[ChatMessage], **kwargs: object) -> ChatResponse:
        raise NotImplementedError

    def stream_chat(self, messages: Sequence[ChatMessage], **kwargs: object):
        raise NotImplementedError

    def complete(self, prompt: str, **kwargs: object):
        raise NotImplementedError

    def stream_complete(self, prompt: str, **kwargs: object):
        raise NotImplementedError
