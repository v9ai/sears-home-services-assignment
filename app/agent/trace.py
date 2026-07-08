"""Shared per-turn latency trace (latency-engineering spec, Scope A).

One ``TurnTrace`` per turn, stamped from both the phone (`app/phone/*`) and web
(`app/ws/routes.py`) call sites via the same idempotent ``.mark(stage)`` — first write
for a stage wins, so a stray re-entry can never clobber the true first timestamp.
``to_record()`` is a pure function of the marks collected so far: a field whose marks
weren't both set is ``None``, never a false ``0``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

Channel = Literal["phone", "web"]
Stage = Literal[
    "t0",
    "stt_done",
    "first_token",
    "first_sentence_ready",
    "first_audio",
    "turn_done",
]


@dataclass
class TurnTrace:
    """Records stage timestamps for one turn; ``to_record()`` derives named deltas."""

    channel: Channel
    session_id: str | uuid.UUID | None = None
    scenario_id: str | None = None
    turn_index: int | None = None
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, stage: Stage, ts: float | None = None) -> None:
        if stage not in self.marks:
            self.marks[stage] = ts if ts is not None else time.monotonic()

    def _delta_ms(self, start: Stage, end: Stage) -> float | None:
        start_ts = self.marks.get(start)
        end_ts = self.marks.get(end)
        if start_ts is None or end_ts is None:
            return None
        return (end_ts - start_ts) * 1000

    def to_record(self) -> dict[str, float | str | int | None]:
        record: dict[str, float | str | int | None] = {
            "channel": self.channel,
            "session_id": str(self.session_id) if self.session_id is not None else None,
            "scenario_id": self.scenario_id,
            "turn_index": self.turn_index,
            "first_token_to_first_sentence_ms": self._delta_ms(
                "first_token", "first_sentence_ready"
            ),
            "turn_total_ms": self._delta_ms("t0", "turn_done"),
        }
        if self.channel == "phone":
            record["eos_to_stt_ms"] = self._delta_ms("t0", "stt_done")
            record["stt_to_agent_first_token_ms"] = self._delta_ms("stt_done", "first_token")
            record["agent_first_token_to_first_audio_ms"] = self._delta_ms(
                "first_token", "first_audio"
            )
            record["eos_to_first_audio_ms"] = self._delta_ms("t0", "first_audio")
        else:
            record["submit_to_first_token_ms"] = self._delta_ms("t0", "first_token")
            record["submit_to_first_audio_ms"] = self._delta_ms("t0", "first_audio")
        return record


def log_turn_trace(trace: TurnTrace, logger: logging.Logger) -> None:
    record = trace.to_record()
    fields = " ".join(
        f"{key}={value}" for key, value in record.items() if key not in ("channel", "session_id")
    )
    logger.info(
        "turn_trace channel=%s session=%s %s",
        record["channel"],
        record["session_id"],
        fields,
    )
