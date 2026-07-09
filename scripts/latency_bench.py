#!/usr/bin/env python3
"""`make latency` — stage + end-to-end latency bench.

specs/features/2026-07-08-latency-engineering.

Three micro-benchmarks (N=5, p50/p95) isolate a single stage each:

- ``eos_to_stt_ms``   — STT-only timing on a synthetic tone (the same
  ``OpenAITranscriber.transcribe`` call the real phone turn makes right after
  ``mark_end_of_speech``).
- ``llm_ttft_ms``     — one no-tool streaming LLM call. A *lower bound* on the real
  agent's ``stt_to_agent_first_token_ms`` (no system prompt / tool loop overhead) —
  the end-to-end phone bench below measures the real, tool-loop-inclusive number.
- ``tts_first_byte_ms`` — TTS time-to-first-byte for a short line.

End-to-end: ``bench_e2e_web`` drives the scenario matrix through
``evals.live_driver.drive_scenario(collect_latency=True)``; ``bench_e2e_phone`` replays
the same scenarios through the real phone-path primitives (STT, ``run_turn``, TTS, and a
real ``TwilioMediaBridge`` against a local fake socket) with persist/recording IO
excluded (no DB dependency — pre-L7, labeled as such in the report).

Key-gated, skip-loud: exits 0 (not a failure) when a required API key is absent, same
shape as `make eval`. The report always writes and the table always renders; the exit
code only reflects pass/fail when ``LATENCY_GATE_HARD=1`` is set (requirements.md
Decision 3 — advisory until two consecutive all-PASS runs earn the flip).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.latency.budgets import MICRO_BUDGETS_MS, PHONE_E2E, WEB_E2E, E2EBudget  # noqa: E402
from app.phone.latency import percentile  # noqa: E402

N_MICRO_SAMPLES = 5
N_E2E_SCENARIOS = 5
REPORT_SCHEMA_VERSION = 2  # v2: per-channel e2e budgets (web 2000/3500 vs phone 2500/4000)


def _llm_key_env() -> str:
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    return "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"


def missing_keys() -> list[str]:
    """STT + TTS are always OpenAI regardless of ``LLM_PROVIDER`` -- both keys are
    required, a deliberate divergence from `make eval`'s single-key check."""
    needed = {_llm_key_env(), "OPENAI_API_KEY"}
    return sorted(k for k in needed if not os.environ.get(k))


def _synthetic_tone_pcm16(
    seconds: float = 3.0, sample_rate: int = 8000, freq: float = 440.0
) -> bytes:
    """A generated sine tone -- no checked-in binary fixture. Content is discarded (only
    the STT call's *duration* is measured); the e2e phone bench drives the agent off the
    scenario's real pinned caller line instead."""
    n = int(seconds * sample_rate)
    samples = bytearray()
    for i in range(n):
        val = int(3000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples += struct.pack("<h", val)
    return bytes(samples)


async def bench_llm_ttft(llm: Any = None, n: int = N_MICRO_SAMPLES) -> list[float]:
    from llama_index.core.base.llms.types import ChatMessage

    from app.agent.core import get_llm

    llm = llm or get_llm()
    message = ChatMessage(role="user", content="Say the single word 'ready' and nothing else.")
    samples: list[float] = []
    for _ in range(n):
        start = time.monotonic()
        stream = await llm.astream_chat([message])
        async for _chunk in stream:
            samples.append((time.monotonic() - start) * 1000)
            break
    return samples


# One STT provider hang must not own a whole percentile: N=5 makes p95 = max, and the
# 2026-07-09 run recorded a single 60.6 s stalled request as phone p95 (runbook §1
# bench-fidelity RCA item 3). Bounded + one retry; a second hang lets the elapsed
# (~2× cap) stand as the sample — bounded, never discarded.
STT_BENCH_TIMEOUT_S = 15.0


async def _transcribe_bounded(transcriber, pcm16: bytes, rate: int) -> None:  # noqa: ANN001
    try:
        await asyncio.wait_for(transcriber.transcribe(pcm16, rate), STT_BENCH_TIMEOUT_S)
    except TimeoutError:
        try:
            await asyncio.wait_for(transcriber.transcribe(pcm16, rate), STT_BENCH_TIMEOUT_S)
        except TimeoutError:
            pass


async def bench_stt_only(n: int = N_MICRO_SAMPLES) -> list[float]:
    from app.phone.stt import OpenAITranscriber

    transcriber = OpenAITranscriber()
    pcm16 = _synthetic_tone_pcm16()
    samples: list[float] = []
    for _ in range(n):
        start = time.monotonic()
        await _transcribe_bounded(transcriber, pcm16, 8000)
        samples.append((time.monotonic() - start) * 1000)
    return samples


async def bench_tts_ttfb(n: int = N_MICRO_SAMPLES) -> list[float]:
    # The PRODUCTION path for this constant string (runbook §1 bench-fidelity RCA
    # item 1): it is PHONE_TOOL_FILLER, a CACHED_STRINGS member that P0-1 serves from
    # the disk cache — benching raw `synthesize` measured the provider TTFB floor the
    # caller never hears. Dynamic-sentence TTS cost still shows up in the e2e rows'
    # first-audio segment.
    from app.agent.fillers import PHONE_TOOL_FILLER
    from app.agent.tts_cache import prewarm, synthesize_cached

    await prewarm(("mp3",))
    samples: list[float] = []
    for _ in range(n):
        start = time.monotonic()
        async for chunk in synthesize_cached(PHONE_TOOL_FILLER):
            if chunk:
                samples.append((time.monotonic() - start) * 1000)
                break
    return samples


async def bench_e2e_web(scenarios: list[Any], m: int) -> list[dict]:
    from app.agent.core import get_llm
    from evals.live_driver import drive_scenario

    llm = get_llm()
    records: list[dict] = []
    for scenario in scenarios[:m]:
        fixture = await drive_scenario(scenario, llm=llm, collect_latency=True)
        records.extend(fixture["trace"])
    return records


async def bench_e2e_phone(scenarios: list[Any], m: int) -> list[dict]:
    # NOTE: the phone media transport is now Pipecat (`app/voice`), which owns µ-law
    # framing, VAD/end-of-speech, and audio emission — the pieces the old
    # `app.phone.bridge.TwilioMediaBridge` used to time here. This bench therefore
    # measures the provider-independent LLM+TTS stack (end-of-speech → first audio) via the
    # same `run_turn`/`synthesize` path; live per-call phone latency is captured directly
    # by Pipecat's pipeline metrics (`PipelineParams(enable_metrics=True)` in
    # `app/voice/bot.py`).
    from llama_index.core.memory import ChatMemoryBuffer

    from app.agent.core import SentenceReady, get_llm, run_turn
    from app.agent.trace import TurnTrace
    from app.agent.tts import synthesize
    from app.contracts import CaseFile
    from app.phone.stt import OpenAITranscriber

    llm = get_llm()
    transcriber = OpenAITranscriber()
    pcm16 = _synthetic_tone_pcm16()
    records: list[dict] = []
    for i, scenario in enumerate(scenarios[:m]):
        case_file = CaseFile()
        memory = ChatMemoryBuffer.from_defaults(llm=llm)
        trace = TurnTrace(channel="phone", scenario_id=scenario.id, turn_index=i)

        trace.mark("t0")  # end-of-speech reference (Pipecat's VAD marks this on a live call)
        await _transcribe_bounded(transcriber, pcm16, 8000)
        trace.mark("stt_done")

        user_text = scenario.turns[0].caller

        # Start TTS the moment the first sentence streams — the Pipecat pipeline
        # synthesizes per-sentence as they arrive; draining the whole turn first
        # overstates eos→first-audio (runbook §1 bench-fidelity RCA item 2).
        async def _mark_first_audio(text: str, trace=trace) -> None:  # noqa: ANN001
            async for _chunk in synthesize(text, response_format="pcm"):
                trace.mark("first_audio")  # first synthesized audio out of the LLM+TTS stack
                break

        first_audio_task: asyncio.Task | None = None
        async for event in run_turn(case_file, memory, user_text, llm=llm, trace=trace):
            if isinstance(event, SentenceReady) and first_audio_task is None:
                first_audio_task = asyncio.create_task(_mark_first_audio(event.text))

        if first_audio_task is not None:
            await first_audio_task
        trace.mark("turn_done")
        records.append(trace.to_record())
    return records


def _stage_result(samples_ms: list[float], budget_ms: float) -> dict[str, Any]:
    p50 = percentile(samples_ms, 0.50) if samples_ms else 0.0
    p95 = percentile(samples_ms, 0.95) if samples_ms else 0.0
    return {
        "samples_ms": samples_ms,
        "p50": p50,
        "p95": p95,
        "budget_ms": budget_ms,
        "pass": bool(samples_ms) and p50 <= budget_ms,
    }


def _e2e_summary(records: list[dict], field: str, budget: E2EBudget) -> dict[str, Any]:
    values = [r[field] for r in records if r.get(field) is not None]
    p50 = percentile(values, 0.50) if values else None
    p95 = percentile(values, 0.95) if values else None
    passed = p50 is not None and p95 is not None and p50 <= budget.p50_ms and p95 <= budget.p95_ms
    return {
        "records": records,
        f"p50_{field}": p50,
        f"p95_{field}": p95,
        "budget_p50_ms": budget.p50_ms,
        "budget_p95_ms": budget.p95_ms,
        "pass": passed,
    }


def build_report(
    micro: dict[str, list[float]],
    e2e_web: list[dict],
    e2e_phone: list[dict],
    *,
    llm_provider: str,
    timestamp: str,
) -> dict[str, Any]:
    micro_report = {
        name: _stage_result(samples, MICRO_BUDGETS_MS[name]) for name, samples in micro.items()
    }
    web_summary = _e2e_summary(e2e_web, "submit_to_first_audio_ms", WEB_E2E)
    phone_summary = _e2e_summary(e2e_phone, "eos_to_first_audio_ms", PHONE_E2E)
    phone_summary["note"] = (
        "pre-L7 (no persist/recording IO) -- see a live call's turn_trace log line for "
        "the true, L7-inclusive turn_total_ms"
    )

    overall_pass = (
        all(stage["pass"] for stage in micro_report.values())
        and web_summary["pass"]
        and phone_summary["pass"]
    )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "timestamp": timestamp,
        "llm_provider": llm_provider,
        "micro_benchmarks": micro_report,
        "end_to_end": {"web": web_summary, "phone": phone_summary},
        "budgets_ms": {
            **MICRO_BUDGETS_MS,
            "web_e2e_p50_ms": WEB_E2E.p50_ms,
            "web_e2e_p95_ms": WEB_E2E.p95_ms,
            "phone_e2e_p50_ms": PHONE_E2E.p50_ms,
            "phone_e2e_p95_ms": PHONE_E2E.p95_ms,
        },
        "overall_pass": overall_pass,
    }


def write_report(report: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (REPO_ROOT / "data" / "latency")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['timestamp']}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def render_table(report: dict[str, Any]) -> str:
    lines = [f"== latency report ({report['timestamp']}, provider={report['llm_provider']}) =="]
    lines.append(f"{'stage':<20}{'p50':>10}{'p95':>10}{'budget':>10}  result")
    for name, stage in report["micro_benchmarks"].items():
        status = "PASS" if stage["pass"] else "FAIL"
        p50, p95, budget = stage["p50"], stage["p95"], stage["budget_ms"]
        lines.append(f"{name:<20}{p50:>10.0f}{p95:>10.0f}{budget:>10.0f}  {status}")
    web = report["end_to_end"]["web"]
    phone = report["end_to_end"]["phone"]
    lines.append("")
    lines.append(
        f"e2e web   submit->first-audio  p50={web.get('p50_submit_to_first_audio_ms')} "
        f"p95={web.get('p95_submit_to_first_audio_ms')}  {'PASS' if web['pass'] else 'FAIL'}"
    )
    lines.append(
        f"e2e phone eos->first-audio     p50={phone.get('p50_eos_to_first_audio_ms')} "
        f"p95={phone.get('p95_eos_to_first_audio_ms')}  {'PASS' if phone['pass'] else 'FAIL'}"
        f"  ({phone['note']})"
    )
    lines.append("")
    lines.append(f"overall: {'PASS' if report['overall_pass'] else 'FAIL'}")
    return "\n".join(lines)


async def _run_live() -> dict[str, Any]:
    from datetime import UTC, datetime

    from app.agent.core import get_llm
    from evals.scenarios.schema import load_scenarios

    llm_provider = os.environ.get("LLM_PROVIDER", "deepseek")
    llm = get_llm()

    micro = {
        "eos_to_stt_ms": await bench_stt_only(),
        "llm_ttft_ms": await bench_llm_ttft(llm=llm),
        "tts_first_byte_ms": await bench_tts_ttfb(),
    }
    scenarios = [s for s in load_scenarios() if not s.canary]
    e2e_web = await bench_e2e_web(scenarios, N_E2E_SCENARIOS)
    e2e_phone = await bench_e2e_phone(scenarios, N_E2E_SCENARIOS)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return build_report(micro, e2e_web, e2e_phone, llm_provider=llm_provider, timestamp=timestamp)


def main() -> int:
    missing = missing_keys()
    if missing:
        print(
            f"WARNING: {', '.join(missing)} not set - skipping make latency "
            "(LLM + STT/TTS keys required)."
        )
        print("This is a SKIP, not a pass — see tech-stack.md -> Evaluation.")
        return 0

    # The app registers this at startup (app/main.py); the bench process must do it
    # itself or every trace record reports llm_calls=0 and the P2-1 round-trip count
    # is invisible exactly where it's needed.
    from app.agent.instrumentation import register_instrumentation

    register_instrumentation()

    report = asyncio.run(_run_live())
    path = write_report(report)
    print(render_table(report))
    print(f"report written: {path}")

    if os.environ.get("LATENCY_GATE_HARD", "").lower() in ("1", "true", "yes"):
        return 0 if report["overall_pass"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
