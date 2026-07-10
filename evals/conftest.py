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


def _drop_cached_db_engines() -> None:
    """Clear the app's cached async engines so the next DB call rebuilds its pool.

    `app.db.base` (lru_cache) and `app.db.matching` (module globals) bind their
    asyncpg pool to the FIRST event loop that touches them. We only drop the cached
    references — we do NOT `await matching.reset_engine()` here: its `dispose()` runs
    against the prior (now-closed) loop and itself raises the cross-loop error.
    Dropping the refs lets each factory rebuild in the live loop; the orphaned pool
    is garbage-collected.
    """
    import app.db.base as _base
    import app.db.matching as _matching

    _base.get_engine.cache_clear()
    _base.get_sessionmaker.cache_clear()
    _matching._engine = None
    _matching._sessionmaker = None


@pytest.fixture(autouse=True)
def _reset_db_engines():
    """Rebind the app's cached async DB engines to each test's own event loop.

    Under `asyncio_mode = "auto"` every test gets a fresh loop, so a later DB-touching
    live drive (e.g. the booking persona) reused an engine pinned to an earlier,
    closed loop and hit asyncpg's "attached to a different loop" — which the drive's
    DB guard swallowed into a silent SKIP. This resets the caches per test so each
    drive rebuilds its pool in its own loop.
    """
    _drop_cached_db_engines()
    yield
    _drop_cached_db_engines()


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
