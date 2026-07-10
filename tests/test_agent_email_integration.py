"""Agent-loop ↔ email integration: the LLM's `send_image_upload_link` tool call driven
through the real `AgentWorkflow` via `run_turn` (COORDINATION.md §4 stub seam).

`tests/test_visual_tools.py` covers the tool with hand-seeded contextvars and
`tests/test_agent_core.py` drives the loop for the core/scheduling tools — but nothing
exercised the seam between them for email: `run_turn` setting `current_session_id` /
`current_case_file`, LlamaIndex dispatching the scripted tool call, and the tool's
result string landing back in agent memory where the model can read it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.tools.types import BaseTool

from app.agent.core import ToolInvoked, run_turn
from app.agent.prompts import build_system_prompt
from app.contracts import CaseFile
from app.email import backend as email_backend
from app.uploads.store import InMemoryUploadStore, set_store
from tests.fakes import FakeFunctionCallingLLM, ScriptedToolCall, ScriptedTurn


class RecordingFakeLLM(FakeFunctionCallingLLM):
    """FakeFunctionCallingLLM that also records the chat history of every LLM round —
    the literal messages the model would see, tool results included. (`run_turn`'s
    ChatMemoryBuffer is not written back by AgentWorkflow, so it can't serve as this
    seam; session continuity in the app is rebuilt from transcripts instead.)"""

    _seen_histories: list[list[ChatMessage]] = PrivateAttr(default_factory=list)

    async def astream_chat_with_tools(
        self,
        tools: Sequence[BaseTool],
        user_msg: str | ChatMessage | None = None,
        chat_history: list[ChatMessage] | None = None,
        **kwargs: object,
    ):
        self._seen_histories.append(list(chat_history or []))
        return await super().astream_chat_with_tools(
            tools, user_msg=user_msg, chat_history=chat_history, **kwargs
        )

    def seen_text(self) -> str:
        return "\n".join(str(m) for history in self._seen_histories for m in history)


@pytest.fixture
def upload_store():
    s = InMemoryUploadStore()
    set_store(s)
    return s


@pytest.fixture(autouse=True)
def _console_email(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    email_backend.reset_email_backend()
    yield
    email_backend.reset_email_backend()


async def _drain(agen):
    events = []
    async for event in agen:
        events.append(event)
    return events


def _send_link_script(email: str, text: str) -> list[ScriptedTurn]:
    """One caller turn: the LLM calls `send_image_upload_link(email)` then speaks."""
    return [
        ScriptedTurn(
            tool_calls=[
                ScriptedToolCall(tool_name="send_image_upload_link", tool_kwargs={"email": email})
            ]
        ),
        ScriptedTurn(text=text),
    ]


async def test_llm_tool_call_sends_upload_email_through_the_loop(upload_store) -> None:
    llm = FakeFunctionCallingLLM(
        script=_send_link_script("caller@example.com", "Link sent — check your email.")
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    session_id = uuid.uuid4()

    events = await _drain(
        run_turn(case_file, memory, "can you email me the link?", session_id=session_id, llm=llm)
    )

    assert [e.tool_name for e in events if isinstance(e, ToolInvoked)] == ["send_image_upload_link"]

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert console.sent[0]["to"] == "caller@example.com"
    assert "http://localhost:8000/upload/" in console.sent[0]["body"]

    # The tool saw run_turn's contextvars: record attached to THIS session, case file updated.
    record = await upload_store.latest_for_session(session_id)
    assert record is not None and record.email == "caller@example.com"
    assert case_file.customer.email == "caller@example.com"


async def test_spoken_email_is_normalized_through_the_loop(upload_store) -> None:
    llm = FakeFunctionCallingLLM(
        script=_send_link_script("D dot Martinez99 at Gmail dot com.", "Sent it over.")
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    session_id = uuid.uuid4()

    await _drain(
        run_turn(case_file, memory, "email me the upload link", session_id=session_id, llm=llm)
    )

    console = email_backend.get_email_backend()
    assert len(console.sent) == 1
    assert console.sent[0]["to"] == "d.martinez99@gmail.com"
    assert case_file.customer.email == "d.martinez99@gmail.com"


async def test_invalid_email_feeds_reconfirm_result_to_model_without_side_effects(
    upload_store,
) -> None:
    llm = RecordingFakeLLM(
        script=_send_link_script("not an email", "Sorry, let me re-check that address.")
    )
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)
    session_id = uuid.uuid4()

    events = await _drain(
        run_turn(case_file, memory, "email me the link", session_id=session_id, llm=llm)
    )

    # The tool WAS dispatched — the rejection is the tool's answer, not a skipped call.
    assert any(
        isinstance(e, ToolInvoked) and e.tool_name == "send_image_upload_link" for e in events
    )

    console = email_backend.get_email_backend()
    assert console.sent == []
    assert await upload_store.latest_for_session(session_id) is None
    assert case_file.customer.email is None

    # The re-confirm instruction reached the model's next round, so it can act on it.
    assert "doesn't look like a valid email" in llm.seen_text()


async def test_missing_session_degrades_gracefully_through_the_loop(upload_store) -> None:
    llm = RecordingFakeLLM(script=_send_link_script("caller@example.com", "One moment please."))
    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=llm)

    await _drain(run_turn(case_file, memory, "email me the link", llm=llm))

    console = email_backend.get_email_backend()
    assert console.sent == []
    assert "couldn't find an active session" in llm.seen_text()


def test_system_prompt_carries_the_image_upload_contract() -> None:
    prompt = build_system_prompt(CaseFile())
    assert "send_image_upload_link" in prompt
    assert "spell it back character by character" in prompt
    assert "check_image_analysis" in prompt
