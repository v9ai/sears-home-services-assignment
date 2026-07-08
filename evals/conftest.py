"""Shared fixtures/hooks for the DeepEval gate (`make eval`).

tech-stack.md → Evaluation: `make eval` must skip loudly (never silently green, never
a hard failure) when the judge provider's API key is absent. The judge runs on
DeepSeek by default (tech-stack.md "Model-provider boundary" — DeepSeek for all LLM
calls); `EVAL_JUDGE_PROVIDER=openai` opts back into `gpt-4o`. This conftest only
affects collection under `evals/` — `tests/` (the `make test` suite) is unaffected.
"""

from __future__ import annotations

import os
import warnings

import pytest

from evals import thresholds


def _missing_reason(key_env: str) -> str:
    return (
        f"{key_env} is not set — DeepEval judge calls "
        f"(provider: {thresholds.judge_provider()}) require it. "
        "`make eval` is SKIPPED (offline CI), not passed and not failed."
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    key_env = thresholds.judge_key_env()
    if os.environ.get(key_env):
        return
    reason = _missing_reason(key_env)
    warnings.warn(reason, stacklevel=1)
    print(f"\nWARNING: {reason}\n")
    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        item.add_marker(skip_marker)
