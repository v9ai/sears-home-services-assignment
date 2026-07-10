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
    e2e_pipecat: list[dict] | None = None,
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
    end_to_end = {"web": web_summary, "phone": phone_summary}
    budgets_ms = {
        **MICRO_BUDGETS_MS,
        "web_e2e_p50_ms": WEB_E2E.p50_ms,
        "web_e2e_p95_ms": WEB_E2E.p95_ms,
        "phone_e2e_p50_ms": PHONE_E2E.p50_ms,
        "phone_e2e_p95_ms": PHONE_E2E.p95_ms,
    }

    # Pipecat-native rows (loop v2 q0-4): the production pipeline's LLM->TTS half,
    # gated against the phone envelope (it IS the phone path). Optional so pre-q0-4
    # reports and offline tests keep their exact shape.
    if e2e_pipecat is not None:
        pipecat_summary = _e2e_summary(e2e_pipecat, "pipecat_eos_to_first_audio_ms", PHONE_E2E)
        pipecat_summary["note"] = (
            "production Pipecat wiring, real LLM+TTS, scripted STT (STT cost lives in "
            "the eos_to_stt_ms micro row)"
        )
        end_to_end["pipecat"] = pipecat_summary
        budgets_ms["pipecat_e2e_p50_ms"] = PHONE_E2E.p50_ms
        budgets_ms["pipecat_e2e_p95_ms"] = PHONE_E2E.p95_ms

    overall_pass = all(stage["pass"] for stage in micro_report.values()) and all(
        summary["pass"] for summary in end_to_end.values()
    )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "timestamp": timestamp,
        "llm_provider": llm_provider,
        "micro_benchmarks": micro_report,
        "end_to_end": end_to_end,
        "budgets_ms": budgets_ms,
        "overall_pass": overall_pass,
    }


def write_report(report: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (REPO_ROOT / "data" / "latency")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['timestamp']}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


# --- measurement envelope (loop v2 §2, q0-2): one MEASUREMENT = N consecutive runs ---
MEASUREMENT_SCHEMA_VERSION = 3

_E2E_MEDIAN_FIELDS = {
    "web": ("p50_submit_to_first_audio_ms", "p95_submit_to_first_audio_ms"),
    "phone": ("p50_eos_to_first_audio_ms", "p95_eos_to_first_audio_ms"),
    "pipecat": ("p50_pipecat_eos_to_first_audio_ms", "p95_pipecat_eos_to_first_audio_ms"),
}


def _median_and_noise(values: list[float]) -> tuple[float, float]:
    """Median of per-run values + noise_pct = (max-min)/median*100 (loop v2 §2)."""
    med = percentile(values, 0.50)
    noise = round((max(values) - min(values)) / med * 100, 1) if med else 0.0
    return med, noise


def build_measurement(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold N single-run reports (schema v2) into one MEASUREMENT (schema v3).

    Stage/e2e verdicts use the MEDIAN across runs — one hung provider call can no
    longer flip a verdict (v1's ±40% single-run variance lesson) — and noise_pct is
    recorded per stage so accept thresholds calibrate to measured noise.
    """
    stages: dict[str, Any] = {}
    for name in reports[0]["micro_benchmarks"]:
        p50s = [r["micro_benchmarks"][name]["p50"] for r in reports]
        budget = reports[0]["micro_benchmarks"][name]["budget_ms"]
        median_p50, noise_pct = _median_and_noise(p50s)
        stages[name] = {
            "p50s": p50s,
            "median_p50": median_p50,
            "noise_pct": noise_pct,
            "budget_ms": budget,
            "pass": median_p50 <= budget,
        }

    e2e: dict[str, Any] = {}
    for channel, (p50_field, p95_field) in _E2E_MEDIAN_FIELDS.items():
        if channel not in reports[0]["end_to_end"]:
            continue  # optional channel (e.g. pipecat pre-q0-4 / keys absent)
        summaries = [r["end_to_end"][channel] for r in reports]
        p50s = [s.get(p50_field) for s in summaries]
        p95s = [s.get(p95_field) for s in summaries]
        entry: dict[str, Any] = {
            "p50s": p50s,
            "p95s": p95s,
            "budget_p50_ms": summaries[0].get("budget_p50_ms"),
            "budget_p95_ms": summaries[0].get("budget_p95_ms"),
        }
        if any(v is None for v in p50s + p95s):
            entry["pass"] = False  # a run with no data fails the measurement, never skips
        else:
            entry["median_p50"], entry["noise_pct"] = _median_and_noise(p50s)
            entry["median_p95"], _ = _median_and_noise(p95s)
            entry["pass"] = (
                entry["median_p50"] <= entry["budget_p50_ms"]
                and entry["median_p95"] <= entry["budget_p95_ms"]
            )
        e2e[channel] = entry

    overall_pass = all(s["pass"] for s in stages.values()) and all(c["pass"] for c in e2e.values())
    return {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "kind": "measurement",
        "timestamp": reports[-1]["timestamp"],
        "llm_provider": reports[-1]["llm_provider"],
        "runs": [r["timestamp"] for r in reports],
        "stages": stages,
        "e2e": e2e,
        "overall_pass": overall_pass,
    }


def write_measurement(measurement: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (REPO_ROOT / "data" / "latency")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{measurement['timestamp']}-measurement.json"
    path.write_text(json.dumps(measurement, indent=2))
    return path


def render_measurement_table(measurement: dict[str, Any]) -> str:
    lines = [
        f"== MEASUREMENT ({len(measurement['runs'])} runs: "
        f"{', '.join(measurement['runs'])}; provider={measurement['llm_provider']}) ==",
        f"{'stage':<22}{'median p50':>12}{'noise%':>8}{'budget':>9}  result",
    ]
    for name, s in measurement["stages"].items():
        status = "PASS" if s["pass"] else "FAIL"
        lines.append(
            f"{name:<22}{s['median_p50']:>12.0f}{s['noise_pct']:>8.1f}"
            f"{s['budget_ms']:>9.0f}  {status}"
        )
    for channel, c in measurement["e2e"].items():
        status = "PASS" if c["pass"] else "FAIL"
        if "median_p50" in c:
            lines.append(
                f"{'e2e ' + channel:<22}{c['median_p50']:>12.0f}{c['noise_pct']:>8.1f}"
                f"{c['budget_p50_ms']:>9.0f}  {status} "
                f"(median p95 {c['median_p95']:.0f} vs {c['budget_p95_ms']:.0f})"
            )
        else:
            lines.append(f"{'e2e ' + channel:<22}{'no data':>12}  {status}")
    lines.append(f"measurement overall: {'PASS' if measurement['overall_pass'] else 'FAIL'}")
    return "\n".join(lines)


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
    pipecat = report["end_to_end"].get("pipecat")
    if pipecat is not None:
        lines.append(
            f"e2e pipecat eos->first-audio   "
            f"p50={pipecat.get('p50_pipecat_eos_to_first_audio_ms')} "
            f"p95={pipecat.get('p95_pipecat_eos_to_first_audio_ms')}  "
            f"{'PASS' if pipecat['pass'] else 'FAIL'}  ({pipecat.get('note', '')})"
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

    # Pipecat-native rows (q0-4): only when the CONFIGURED voice providers' keys are
    # present; their absence is reported loudly (an empty-records FAIL row), never a
    # silent skip.
    from scripts.latency_pipecat import bench_e2e_pipecat, needed_keys

    pipecat_missing = needed_keys()
    if pipecat_missing:
        print(
            f"WARNING: pipecat e2e rows FAIL — missing {', '.join(pipecat_missing)} "
            "for the configured voice providers."
        )
        e2e_pipecat: list[dict] = []
    else:
        e2e_pipecat = await bench_e2e_pipecat(scenarios, N_E2E_SCENARIOS)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return build_report(
        micro,
        e2e_web,
        e2e_phone,
        llm_provider=llm_provider,
        timestamp=timestamp,
        e2e_pipecat=e2e_pipecat,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="stage + e2e latency bench")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run the full bench N times sequentially and fold the runs into one "
        "MEASUREMENT envelope (median + noise_pct per stage; loop v2 §2). N=3 is "
        "one loop-v2 MEASUREMENT.",
    )
    # argv=None means "no CLI args" (test-friendly); __main__ passes sys.argv[1:].
    args = parser.parse_args(argv if argv is not None else [])
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

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

    reports: list[dict[str, Any]] = []
    for i in range(args.repeat):
        report = asyncio.run(_run_live())
        reports.append(report)
        path = write_report(report)
        print(render_table(report))
        print(f"report written: {path}")
        if args.repeat > 1:
            print(f"[measurement run {i + 1}/{args.repeat} complete]")

    gate_hard = os.environ.get("LATENCY_GATE_HARD", "").lower() in ("1", "true", "yes")

    if args.repeat > 1:
        measurement = build_measurement(reports)
        mpath = write_measurement(measurement)
        print(render_measurement_table(measurement))
        print(f"measurement written: {mpath}")
        if gate_hard:
            return 0 if measurement["overall_pass"] else 1
        return 0

    if gate_hard:
        return 0 if reports[0]["overall_pass"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
