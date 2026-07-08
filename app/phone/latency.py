"""End-of-speech -> first-audio latency instrumentation (plan.md group 5).

Budget (requirements.md): p50 <= 2.5 s, p95 <= 4 s. This is a logging-only instrument --
no metrics backend is in scope for the take-home -- but it keeps a rolling in-memory
sample so a live-call session (or a test) can assert the percentiles directly instead of
grepping logs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

P50_BUDGET_S = 2.5
P95_BUDGET_S = 4.0

logger = logging.getLogger("app.phone.latency")


def _percentile(samples: list[float], p: float) -> float:
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
        return _percentile(self.samples, 0.50)

    @property
    def p95(self) -> float:
        return _percentile(self.samples, 0.95)

    def within_budget(self) -> bool:
        if not self.samples:
            return True
        return self.p50 <= P50_BUDGET_S and self.p95 <= P95_BUDGET_S
