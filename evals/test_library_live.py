"""Live end-to-end gate for the flag-gated appliance-library RAG path.

The fixture-based library scenarios (`evals/scenarios/library/`) judge recorded
transcripts and never exercise `search_appliance_library`; the retrieval gate
(`evals/test_library_retrieval.py`) hits the store directly, bypassing the tool
flag. This module closes the remaining gap: drive the REAL agent (`run_turn`, real
`get_llm()` provider, real embedded Qdrant built by `scripts.ingest_library.ingest`)
with `LIBRARY_RAG_ENABLED=1` and assert the tool loop actually reaches the library
for a brand question and answers grounded in the caller's brand.

Lives under `evals/` to inherit `evals/conftest.py`'s judge-key skip posture (a live
LLM call is required); additionally guards on the `LLM_PROVIDER` key the agent
itself needs, mirroring `evals/test_library_retrieval.py`. Assertions stay tolerant
of LLM nondeterminism: tool invocation + brand mention, never exact wording.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.ingest_library import ingest


def _require_agent_llm_or_skip() -> None:
    if os.environ.get("LLM_PROVIDER", "deepseek").strip().lower() == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set — live agent run needs a real LLM")
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set — live agent run needs a real LLM")


@pytest.fixture()
def library_enabled_agent(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Real Qdrant index in a tmp dir + `LIBRARY_RAG_ENABLED=1`, with the module-level
    tool registration (`app/tools/library_tools.py` computes ``TOOLS`` at import — same
    reload seam `tests/test_library_flag.py` uses) re-evaluated under the flag, and
    restored to the flag-off default afterwards so no other test inherits the tool."""
    qdrant_path = tmp_path_factory.mktemp("qdrant_live_gate")
    client, _index = ingest(str(qdrant_path))
    client.close()

    monkeypatch.setenv("QDRANT_PATH", str(qdrant_path))
    monkeypatch.setenv("LIBRARY_RAG_ENABLED", "1")

    from app.knowledge import library_store
    from app.tools import library_tools

    library_store.set_store(None)  # drop any cached store pointing at another path
    importlib.reload(library_tools)
    try:
        yield
    finally:
        monkeypatch.delenv("LIBRARY_RAG_ENABLED", raising=False)
        importlib.reload(library_tools)
        library_store.set_store(None)


@pytest.mark.asyncio
async def test_live_agent_answers_brand_question_from_library(
    library_enabled_agent: None,
) -> None:
    _require_agent_llm_or_skip()
    from llama_index.core.memory import ChatMemoryBuffer

    from app.agent.core import SentenceReady, ToolInvoked, run_turn
    from app.contracts import CaseFile

    case_file = CaseFile()
    memory = ChatMemoryBuffer.from_defaults(llm=None)

    # An out-of-tree problem (mold/odor is in no washer.yaml symptom tree) drives the
    # documented fallback path: deterministic lookup misses -> search_appliance_library.
    # The final nudge turn only matters if the model answered generically without the
    # tool — a caller explicitly asking for the library makes invocation near-certain
    # while keeping the assertion about real end-to-end behavior, not exact wording.
    caller_turns = [
        "Hi, my Kenmore washer's detergent drawer keeps getting moldy and smells musty "
        "— what should I do about it?",
        "Could you check your appliance library for any Kenmore-specific guidance on this?",
    ]

    tools_invoked: list[str] = []
    agent_texts: list[str] = []
    for caller_text in caller_turns:
        if caller_text is caller_turns[-1] and "search_appliance_library" in tools_invoked:
            break
        sentences: list[str] = []
        async for event in run_turn(case_file, memory, caller_text, session_id=None):
            if isinstance(event, ToolInvoked):
                tools_invoked.append(event.tool_name)
            elif isinstance(event, SentenceReady):
                sentences.append(event.text)
        agent_texts.append(" ".join(sentences))

    assert "search_appliance_library" in tools_invoked, (
        f"agent never reached the library tool; tools invoked: {tools_invoked}"
    )
    full_reply = " ".join(agent_texts).lower()
    assert "kenmore" in full_reply, f"reply never mentions the caller's brand: {full_reply!r}"


def test_ingest_module_is_importable_from_repo_root() -> None:
    """Same worktree-sanity guard as evals/test_library_retrieval.py — a stale
    sys.path would otherwise mask import errors in the live test above."""
    from scripts.ingest_library import REPO_ROOT

    assert (Path(REPO_ROOT) / "app" / "tools").is_dir()
