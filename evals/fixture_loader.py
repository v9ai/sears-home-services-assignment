"""Recorded fixture transcripts (COORDINATION.md §4 stub seam).

Fixture mode: until the real agent lands, `scripts/transcript_runner.py` and the
DeepEval harness read pre-recorded transcripts from here instead of driving
`app.agent`. Each fixture stands in for "the agent said X and ended up with case
file Y" for a given scenario id. Flipping to live-agent-recorded transcripts is an
integration-time change the lead makes (see plan.md → Integration deltas) — this
module must not import `app.agent`.

Fixture JSON shape::

    {"turns": [{"role": "user"|"agent", "text": str}, ...],
     "case_file": {...CaseFile-shaped dict, app.contracts.CaseFile...},
     "flags": {"safety_interrupt": bool, "booking_row": bool, "reasked_fields": [str]}}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"


class FixtureNotFoundError(FileNotFoundError):
    """No recorded fixture transcript for a scenario id."""


def load_fixture(scenario_id: str, root: Path | None = None) -> dict[str, Any]:
    directory = root or FIXTURES_DIR
    path = directory / f"{scenario_id}.json"
    if not path.exists():
        raise FixtureNotFoundError(
            f"no recorded fixture transcript for scenario {scenario_id!r} (expected {path})"
        )
    return json.loads(path.read_text())
