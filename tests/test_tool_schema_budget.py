"""O13 (latency-engineering): the LLM-visible tool descriptions are re-uploaded as
prefill on EVERY agent LLM round — keep the total terse. Dev/mechanics prose belongs
in `#` comments above the functions, not in the docstrings the model pays for."""

from __future__ import annotations

import pytest

from app.tools.registry import get_tools

# ~600 tokens at ~4 chars/token. Raising this ceiling is an o13 regression — justify
# in specs/features/2026-07-08-latency-engineering (plan P2/O13) before touching it.
MAX_TOTAL_DESCRIPTION_CHARS = 2400

# No single tool description should dominate the shared budget. The largest today is
# book_appointment (~510 chars); this ceiling leaves headroom without letting one tool's
# docstring balloon unnoticed while the total still fits.
MAX_PER_TOOL_DESCRIPTION_CHARS = 700

# Substrings that mark internal/dev prose. These belong in `#` comments above the
# function, not in the LLM-visible docstring the model pays for on every round (module
# policy, top of file). `.md` catches spec filenames (requirements.md, COORDINATION.md);
# `§` catches section pointers.
_INTERNAL_MARKERS = (".md", "§", "o13", "COORDINATION", "TODO", "FIXME")


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


def test_no_single_tool_description_dominates_the_budget():
    for fn in get_tools():
        size = len((fn.__doc__ or "").strip())
        assert size <= MAX_PER_TOOL_DESCRIPTION_CHARS, (
            f"{fn.__name__} docstring is {size} chars > {MAX_PER_TOOL_DESCRIPTION_CHARS} "
            f"— slim it or move mechanics into a `#` comment"
        )


@pytest.mark.parametrize("fn", get_tools(), ids=lambda fn: fn.__name__)
def test_tool_docstrings_do_not_leak_internal_spec_markers(fn):
    """LLM-visible docstrings must not carry internal/dev references (spec filenames,
    section markers, ticket codes) — that prose is re-billed on every agent round and
    belongs in `#` comments (module policy)."""
    doc = fn.__doc__ or ""
    leaked = [m for m in _INTERNAL_MARKERS if m in doc]
    assert not leaked, f"{fn.__name__} docstring leaks internal marker(s) {leaked} to the LLM"
