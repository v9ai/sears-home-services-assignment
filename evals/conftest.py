"""Shared fixtures/hooks for the DeepEval gate (`make eval`).

tech-stack.md → Evaluation: `make eval` must skip loudly (never silently green, never
a hard failure) when `OPENAI_API_KEY` is absent, since judge calls (`gpt-4o`) need it.
This conftest only affects collection under `evals/` — `tests/` (the `make test`
suite) is unaffected regardless of whether the key is set.
"""

from __future__ import annotations

import os
import warnings

import pytest

OPENAI_API_KEY_MISSING_REASON = (
    "OPENAI_API_KEY is not set — DeepEval judge calls (gpt-4o) require it. "
    "`make eval` is SKIPPED (offline CI), not passed and not failed."
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    warnings.warn(OPENAI_API_KEY_MISSING_REASON, stacklevel=1)
    print(f"\nWARNING: {OPENAI_API_KEY_MISSING_REASON}\n")
    skip_marker = pytest.mark.skip(reason=OPENAI_API_KEY_MISSING_REASON)
    for item in items:
        item.add_marker(skip_marker)
