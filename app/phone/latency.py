"""End-of-speech -> first-audio latency instrumentation (plan.md group 5).

Budget (canonical: `specs/latency/budgets.md`, machine SoT `app.latency.budgets`):
phone e2e p50 / p95. This is a logging-only instrument -- no metrics backend is in
scope for the take-home -- but it keeps an in-memory sample list so a live-call
session (or a test) can assert the percentiles directly instead of grepping logs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from app.latency.budgets import PHONE_E2E

# Back-compat aliases: existing importers (tests, docs) keep working; the numbers
# themselves live only in app/latency/budgets.py.
P50_BUDGET_S = PHONE_E2E.p50_s
P95_BUDGET_S = PHONE_E2E.p95_s

logger = logging.getLogger("app.phone.latency")


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)
    return ordered[max(0, idx)]


@dataclass
class LatencyRecorder:
    """Records per-turn end-of-speech -> first-audio elapsed seconds."""

    samples: list[float] = field(default_factory=list)

    def record(self, elapsed_s: float) -> None:
        self.samples.append(elapsed_s)
        over_budget = elapsed_s > P95_BUDGET_S
        level = logging.WARNING if over_budget else logging.INFO
        logger.log(
            level,
            "phone_turn_latency_s=%.3f budget_p50=%.1f budget_p95=%.1f over_budget=%s",
            elapsed_s,
            P50_BUDGET_S,
            P95_BUDGET_S,
            over_budget,
        )

    @property
    def p50(self) -> float:
        return percentile(self.samples, 0.50)

    @property
    def p95(self) -> float:
        return percentile(self.samples, 0.95)

    def within_budget(self) -> bool:
        if not self.samples:
            return True
        return self.p50 <= P50_BUDGET_S and self.p95 <= P95_BUDGET_S
