"""Hermetic-env guard for the voice test package.

`tests/scheduling/conftest.py` loads the repo-root `.env` into `os.environ`
(setdefault) whenever `DATABASE_URL` isn't already exported, and pytest imports it
during collection — so per-deployment voice knobs set in `.env` leak into these
hermetic pipeline tests. Concretely: `FILLER_ENABLED=1` arms `FillerProcessor`
inside `_build_conversation_pipeline`, and its bridge line short-circuits the
eos->first-audio assertions in `test_voice_latency_e2e.py` (the filler's
`TTSStartedFrame` lands ~1 s after end-of-speech no matter how slow the fake LLM
is). Strip the filler knobs for every test in this package; tests that exercise
them opt in explicitly via constructor args or `monkeypatch.setenv`.
"""

from __future__ import annotations

import pytest

_FILLER_ENV_KNOBS = ("FILLER_ENABLED", "FILLER_DELAY_MS")


@pytest.fixture(autouse=True)
def _hermetic_filler_env(monkeypatch):
    for name in _FILLER_ENV_KNOBS:
        monkeypatch.delenv(name, raising=False)
