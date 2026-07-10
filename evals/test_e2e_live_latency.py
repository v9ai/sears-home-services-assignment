"""Live per-turn latency budget — surfaces agent-turn latency regressions in the advisory
lane.

`evals/adaptive_driver.drive_llm_caller` now records the wall-clock of each `run_turn`
span (the agent turn only — caller-LLM think time is the driver's cost, excluded). This
test drives a couple of bounded, diagnostic-only personas (no booking, so no DB
dependency), pools the per-turn latencies, and asserts the p95 is under a deliberately
generous advisory budget. It is not a precise benchmark (make latency owns that) — it's a
cheap tripwire so a gross end-to-end slowdown shows up here instead of only in production.

Advisory lane: live-marked, retried once, never fails the build; SKIPS cleanly without the
agent LLM key (mirrors evals/test_e2e_live_personas.py). Turn counts are small by design.
"""

from __future__ import annotations

import math
import os

import pytest

from evals.adaptive_driver import CallerPersona, drive_llm_caller

pytestmark = pytest.mark.live

# Generous on purpose: this is a regression tripwire, not a target. gpt-4.1-mini / DeepSeek
# conversational turns land a few seconds each; 15s p95 flags a gross slowdown without
# flaking on ordinary provider variance.
BUDGET_P95_S = 15.0


def _require_agent_llm_or_skip() -> None:
    if os.environ.get("LLM_PROVIDER", "deepseek").strip().lower() == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set — live latency drive needs a real LLM")
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set — live latency drive needs a real LLM")


def _p95(values: list[float]) -> float:
    """Nearest-rank p95. For the small samples here it sits at/near the max, which is the
    strict reading we want for a latency tripwire."""
    ordered = sorted(values)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


# Diagnostic-only personas: they ask to understand/fix the problem and explicitly do NOT
# request a technician, so the agent stays on the identify/symptom/troubleshoot path and the
# drive needs no DB. Kept short (max_turns) to bound cost.
_LATENCY_PERSONAS = [
    CallerPersona(
        id="lat_vague",
        goal=(
            "Your refrigerator isn't cooling well. You want to understand what's wrong and "
            "try to fix it yourself. Answer the agent's questions briefly. Do NOT ask to "
            "schedule or book a technician."
        ),
        opening_line="My fridge isn't keeping things cold anymore — what could be wrong?",
        max_turns=4,
    ),
    CallerPersona(
        id="lat_error_code",
        goal=(
            "Your oven shows error code F10 and won't heat. You want to know what the code "
            "means and how to fix it yourself. Answer briefly. Do NOT ask for a technician "
            "visit or a booking."
        ),
        opening_line="My oven is flashing error code F10 and won't heat up — what does that mean?",
        max_turns=4,
    ),
]


@pytest.mark.asyncio
async def test_e2e_live_per_turn_latency_budget() -> None:
    """Pool per-turn `run_turn` wall-clock across a couple of live drives; assert p95 is
    under the advisory budget so a live latency regression trips this lane.

    Each drive's FIRST turn is dropped as warmup: it pays one-time costs production
    amortizes — the cold model connection, tool-registry construction, DB-engine init — and
    over a handful of turns nearest-rank p95 would otherwise collapse onto that single
    cold-start spike. Steady-state per-turn latency is what this tripwire guards; a
    regression that slows every turn still trips it."""
    _require_agent_llm_or_skip()

    latencies: list[float] = []
    for persona in _LATENCY_PERSONAS:
        result = await drive_llm_caller(persona)
        latencies.extend(result["turn_latencies_s"][1:])  # drop warmup turn

    # Guard against a vacuous pass if the drives fizzled and timed almost nothing.
    assert len(latencies) >= 4, f"too few steady-state turns to judge latency: {latencies!r}"

    p95 = _p95(latencies)
    assert p95 < BUDGET_P95_S, (
        f"per-turn run_turn p95 {p95:.1f}s exceeds the {BUDGET_P95_S:.0f}s advisory budget; "
        f"latencies(sorted)={[round(x, 2) for x in sorted(latencies)]}"
    )
