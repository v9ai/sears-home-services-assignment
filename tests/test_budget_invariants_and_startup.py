"""Budget ordering invariants + real-app startup coverage (bugfix-loop T11).

The audit found two unguarded budget invariants (a p50/p95 swap or a
meaningful budget dropping below its perceived counterpart would ship green)
and two never-exercised `app/main.py` branches: the positive
`LATENCY_PROBE_ENABLED` mount (import-time, so tested in a subprocess) and
the three startup hooks (tests always used TestClient without the lifespan).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import app.latency.budgets as budgets_module
from app.latency.budgets import (
    PHONE_E2E,
    PHONE_MEANINGFUL,
    WEB_E2E,
    WEB_MEANINGFUL,
    E2EBudget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "CARTESIA_API_KEY",
    "CARTESIA_VOICE_ID",
    "WEB_TTS_PROVIDER",
)


# --- budget ordering invariants -------------------------------------------------


def _all_e2e_budgets() -> list[E2EBudget]:
    found = [v for v in vars(budgets_module).values() if isinstance(v, E2EBudget)]
    assert len(found) >= 4, "expected at least the four channel budgets"
    return found


def test_every_e2e_budget_has_p50_strictly_below_p95() -> None:
    for budget in _all_e2e_budgets():
        assert budget.p50_ms < budget.p95_ms, f"{budget.name}: p50 must be < p95"


def test_meaningful_budgets_are_not_tighter_than_perceived() -> None:
    # The h1 split's premise: the meaningful reply may take longer than the
    # perceived (filler) audio. A meaningful budget below its perceived
    # counterpart would silently invert the gate's meaning.
    for meaningful, perceived in (
        (PHONE_MEANINGFUL, PHONE_E2E),
        (WEB_MEANINGFUL, WEB_E2E),
    ):
        assert meaningful.p50_ms >= perceived.p50_ms
        assert meaningful.p95_ms >= perceived.p95_ms


# --- app/main.py startup surface --------------------------------------------------


def test_startup_hooks_run_clean_under_the_lifespan(monkeypatch) -> None:
    # TestClient-as-context-manager fires the on_event("startup") handlers —
    # instrumentation registration, startup log, and the TTS prewarm (a no-op
    # here: every provider key is cleared, per the i3 provider-aware gate).
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200


def test_latency_probe_mounts_when_flag_truthy() -> None:
    # The mount is module-import-time, so the positive branch needs a fresh
    # interpreter; a subprocess keeps the running suite's app object pristine.
    # Routers include lazily (_IncludedRouter has no .path); the OpenAPI schema
    # is where mounted paths materialize.
    code = "from app.main import app; print('/debug/latency-probe' in app.openapi()['paths'])"
    env = {k: v for k, v in os.environ.items() if k not in _PROVIDER_KEYS}
    env["LATENCY_PROBE_ENABLED"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == "True", (
        "LATENCY_PROBE_ENABLED=1 must mount /debug/latency-probe on the real app"
    )
