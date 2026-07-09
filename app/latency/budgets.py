"""Single source of truth for every latency budget.

Canonical prose: `specs/latency/budgets.md` — kept in lockstep by
`tests/latency/test_budget_spec_sync.py` (the sync test regex-parses that file's
budget table and asserts dict-equality with `ALL_BUDGETS_MS`).

Numbers originate from `specs/features/2026-07-08-latency-engineering/requirements.md`
("Stage budgets") and `specs/features/2026-07-08-voice-diagnostic-core/requirements.md`
(web tier). To change a budget: edit THIS module and `specs/latency/budgets.md`
together; nowhere else. Every other spec/doc references the canonical doc instead of
restating numbers, and every code consumer (`app/phone/latency.py`,
`scripts/latency_bench.py`, `app/voice/bot.py`, tests) imports from here.

Deliberately a leaf module: zero `app.*` imports, so it is importable from anywhere
(including `scripts/`) with no circular-import risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class StageBudget:
    """One pipeline stage's latency budget, keyed by its canonical trace/report field."""

    name: str  # canonical trace/report field name (e.g. "eos_to_stt_ms")
    budget_ms: float


@dataclass(frozen=True, slots=True)
class E2EBudget:
    """End-to-end percentile budget for one channel."""

    channel: str  # "phone" | "web"
    p50_ms: float
    p95_ms: float

    @property
    def p50_s(self) -> float:
        return self.p50_ms / 1000

    @property
    def p95_s(self) -> float:
        return self.p95_ms / 1000


# --- per-stage budgets (latency-engineering "Stage budgets") --------------------------
EOS_TO_STT: Final = StageBudget("eos_to_stt_ms", 900)
STT_TO_FIRST_TOKEN: Final = StageBudget("stt_to_first_token_ms", 1200)  # bench: llm_ttft_ms
FIRST_TOKEN_TO_FIRST_SENTENCE: Final = StageBudget("first_token_to_first_sentence_ms", 800)
TTS_FIRST_BYTE: Final = StageBudget("tts_first_byte_ms", 500)
FIRST_OUTBOUND_FRAME: Final = StageBudget("first_outbound_frame_ms", 100)
WEB_FIRST_TOKEN: Final = StageBudget("submit_to_first_token_ms", 1000)  # voice-diagnostic-core

# --- end-to-end budgets ----------------------------------------------------------------
PHONE_E2E: Final = E2EBudget("phone", p50_ms=2500, p95_ms=4000)  # eos -> first audio
WEB_E2E: Final = E2EBudget("web", p50_ms=2000, p95_ms=3500)  # submit -> first audio

# --- perceived-latency budgets (assignment §6: the caller's experience matters) ---------
ANSWER_TO_GREETING_MS: Final = 1500
ANSWER_TO_GREETING_CACHED_MS: Final = 500
FILLER_AFTER_EOS_MS: Final = 800

# --- latency-critical tunables recorded centrally (knobs, not budgets) ------------------
# Silero VAD stop-hangover: dead air the caller must leave after finishing speaking.
# Pipecat's default is ~0.8 s; 0.5 s is the recorded deliberate choice (app/voice/bot.py).
VAD_STOP_SECS_DEFAULT: Final = 0.5
# Below this, callers get cut off mid-utterance (false end-of-turn) — overrides under the
# floor are honored but logged (`voice.vad.stop_secs_below_safe_floor`).
VAD_STOP_SECS_MIN_SAFE: Final = 0.4

# --- derived views ----------------------------------------------------------------------
# The bench's micro-benchmark stages (scripts/latency_bench.py), keyed by report field.
MICRO_BUDGETS_MS: Final[dict[str, float]] = {
    "eos_to_stt_ms": EOS_TO_STT.budget_ms,
    "llm_ttft_ms": STT_TO_FIRST_TOKEN.budget_ms,
    "tts_first_byte_ms": TTS_FIRST_BYTE.budget_ms,
}

# Everything, for the spec-sync tests (tests/latency/test_budget_spec_sync.py).
ALL_BUDGETS_MS: Final[dict[str, float]] = {
    EOS_TO_STT.name: EOS_TO_STT.budget_ms,
    STT_TO_FIRST_TOKEN.name: STT_TO_FIRST_TOKEN.budget_ms,
    FIRST_TOKEN_TO_FIRST_SENTENCE.name: FIRST_TOKEN_TO_FIRST_SENTENCE.budget_ms,
    TTS_FIRST_BYTE.name: TTS_FIRST_BYTE.budget_ms,
    FIRST_OUTBOUND_FRAME.name: FIRST_OUTBOUND_FRAME.budget_ms,
    WEB_FIRST_TOKEN.name: WEB_FIRST_TOKEN.budget_ms,
    "phone_e2e_p50_ms": PHONE_E2E.p50_ms,
    "phone_e2e_p95_ms": PHONE_E2E.p95_ms,
    "web_e2e_p50_ms": WEB_E2E.p50_ms,
    "web_e2e_p95_ms": WEB_E2E.p95_ms,
    "answer_to_greeting_ms": ANSWER_TO_GREETING_MS,
    "answer_to_greeting_cached_ms": ANSWER_TO_GREETING_CACHED_MS,
    "filler_after_eos_ms": FILLER_AFTER_EOS_MS,
}
