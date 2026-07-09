"""O13 (latency-engineering): the LLM-visible tool descriptions are re-uploaded as
prefill on EVERY agent LLM round — keep the total terse. Dev/mechanics prose belongs
in `#` comments above the functions, not in the docstrings the model pays for."""

from __future__ import annotations

from app.tools.registry import get_tools

# ~600 tokens at ~4 chars/token. Raising this ceiling is an o13 regression — justify
# in specs/features/2026-07-08-latency-engineering (plan P2/O13) before touching it.
MAX_TOTAL_DESCRIPTION_CHARS = 2400


def test_llm_visible_tool_descriptions_stay_within_budget():
    sizes = {fn.__name__: len((fn.__doc__ or "").strip()) for fn in get_tools()}
    total = sum(sizes.values())
    assert total <= MAX_TOTAL_DESCRIPTION_CHARS, (
        f"tool docstrings total {total} chars > {MAX_TOTAL_DESCRIPTION_CHARS} "
        f"(per-tool: {sizes}) — slim the LLM-visible text, move prose to comments"
    )


def test_every_tool_still_has_a_description():
    for fn in get_tools():
        assert (fn.__doc__ or "").strip(), f"{fn.__name__} lost its LLM-visible docstring"
