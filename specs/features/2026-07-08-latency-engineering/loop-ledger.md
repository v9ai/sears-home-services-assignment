# Latency Loop Ledger
state: running
iteration: 3
live_runs_total: 4
consecutive_all_pass: 0
consecutive_no_accept: 0
branch: latency-loop (note: executor works on `main` — shared working dir makes branch
isolation fictional; `latency-loop` is fast-forwarded to main at loop end)

Durable state for the `/latency-iterate` loop (`.claude/skills/latency-iterate/`).
`data/` is gitignored, so report summaries live here. Counters above are the §1/§8
preconditions' source of truth.

## External change (not a loop iteration) — 2026-07-10 — Pipecat phone-path pass

User-driven fix for the caller-facing dead-air complaint, applied outside the loop
(plan.md "As-built note — Pipecat phone-path latency pass"). `.env` flips
(STT/TTS→cartesia, VOICE_LLM_MODEL=gpt-4.1-mini, VAD_STOP_SECS=0.4, FILLER_ENABLED=1)
+ new `FillerProcessor` in the Pipecat pipeline. **Loop impact:** (a) none of these
move the bench columns — `make latency` drives the pre-Pipecat web/phone primitives,
not `app/voice/bot.py`'s pipeline (a bench-fidelity gap alongside RCA items 1-3);
(b) `.env` now enables the filler, and `tests/scheduling/conftest.py` leaks `.env`
into pytest, so hermetic voice tests strip FILLER_* via `tests/voice/conftest.py` —
keep that guard in mind when adding latency assertions. Gates at time of change:
lint clean on the changed files (pre-existing failures in in-flight bargein/prompts
files), tests/voice 119/119, Cartesia live smoke PASS (TTS synth + STT loopback
through the real `_build_stt`/`_build_tts` factories).

## Iteration 1 — baseline — BLOCKED (incomplete: gates interrupted by parallel work; bootstrap commit never made)

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-09T20:37:10Z",
  "fix_id": "baseline",
  "description": "First loop-owned make latency archive + harness adoption (comparator script, its tests, the skill, this ledger). Neutral fix: no product diff.",
  "baseline_report": "20260709T200404Z.json",
  "after_report": "20260709T203633Z.json",
  "target_metric": null,
  "stages": {
    "eos_to_stt_ms": {"before_p50": 633.5, "after_p50": 779.9, "budget": 900, "delta_pct": 23.1},
    "llm_ttft_ms": {"before_p50": 795.6, "after_p50": 674.1, "budget": 1200, "delta_pct": -15.3},
    "tts_first_byte_ms": {"before_p50": 791.9, "after_p50": 862.5, "budget": 500, "delta_pct": 8.9},
    "web_e2e_p50_ms": {"before_p50": 3255.9, "after_p50": 7573.4, "budget": 2000, "delta_pct": 132.6},
    "phone_e2e_p50_ms": {"before_p50": 3766.7, "after_p50": 8691.7, "budget": 2500, "delta_pct": 130.8}
  },
  "gates": {"lint": "pass", "test": "pass", "eval": "skipped (justified: pure-harness diff, no agent surface)", "latency_overall": false},
  "live_runs_this_iteration": 1,
  "decision": "blocked",
  "commit": null,
  "revert_commit": null,
  "notes": "Two consecutive live runs (200404Z by hand, 203633Z by the loop) show 130% e2e run-to-run swing and both e2e envelopes + tts_first_byte FAIL. Runbook bench-fidelity RCA (2026-07-09) attributes tts_first_byte and web-e2e FAILs to MEASUREMENT artifacts: (1) bench_tts_ttfb bypasses the P0-1 cache on a CACHED string; (2) live_driver drains the whole turn before synthesizing sentences[0] (submit_to_first_audio > turn_total in every record); (3) phone p95 is one-sample-max under N=5, unbounded by any STT timeout. NEXT TARGET REORDER (skill §3.5): `bench-fidelity` before `model-pin` — with 130% run noise and artifact-dominated FAILs, no e2e accept/revert delta is trustworthy; model-pin's own accept decision needs a faithful bench first. Rationale rows: runbook §1 'Bench-fidelity RCA' items 1-3."
}
```

## Iteration 2 — bench-fidelity — ACCEPTED

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-09T21:25:00Z",
  "fix_id": "bench-fidelity",
  "description": "Measure the shipped path: bench_tts_ttfb -> synthesize_cached(PHONE_TOOL_FILLER) after prewarm (P0-1 path); bench_e2e_phone + live_driver start first-sentence TTS at first SentenceReady (as SpeechPipeline does) instead of draining the turn; STT bench calls bounded (15s + one retry, never discarded). No product diff, no budget touched. Reorder rationale recorded in i1 notes (runbook §1 RCA).",
  "baseline_report": "20260709T203633Z.json",
  "after_report": "20260709T211909Z.json",
  "target_metric": "tts_first_byte_ms (+ e2e fidelity)",
  "stages": {
    "eos_to_stt_ms": {"before_p50": 779.8936248291284, "after_p50": 871.2284578941762, "budget": 900, "delta_pct": 11.7},
    "llm_ttft_ms": {"before_p50": 674.1057080216706, "after_p50": 685.116209089756, "budget": 1200, "delta_pct": 1.6},
    "tts_first_byte_ms": {"before_p50": 862.5097500625998, "after_p50": 0.10645785368978977, "budget": 500, "delta_pct": -100.0},
    "web_e2e_p50_ms": {"before_p50": 7573.370832949877, "after_p50": 2659.64691597037, "budget": 2000, "delta_pct": -64.9},
    "phone_e2e_p50_ms": {"before_p50": 8691.744665848091, "after_p50": 3170.695708831772, "budget": 2500, "delta_pct": -63.5}
  },
  "gates": {"lint": "pass", "test": "pass (518, after FK-cleanup repair 2c6be93 for the new appointments.session_id FK)", "eval": "skipped (justified: pure-harness diff — scripts/latency_bench.py + evals/live_driver.py measurement code; no app/agent, app/voice, prompt, or tool-schema surface)", "latency_overall": false},
  "live_runs_this_iteration": 1,
  "decision": "accepted",
  "commit": "9f45867",
  "revert_commit": null,
  "notes": "tts_first_byte FAIL->PASS (cache path, ~0.1ms); phone p95 66954->3251 (STT hang bounded; p95 now under 4000); no PASS->FAIL crossing (eos_to_stt +11.7% run noise, within PASS). Remaining FAILs: web e2e p50 2660/2000, phone e2e p50 3171/2500 — composite rows now faithful; dominant residual = submit_to_first_token on multi-tool turns (2-tool round trips). Collaborator .env flips (STT/TTS->cartesia, VOICE_LLM_MODEL, VAD, FILLER) are app/voice-only; bench-driving knobs unchanged, comparison valid. Ledger committed separately (no amend): rewriting shared-branch history with a live collaborator is unsafe. NEXT: model-pin is bench-invisible (bench does not exercise app/voice; .env already runs gpt-4.1-mini live) -> apply as code-default alignment with mandatory eval, judged as neutral-class with the bench-invisibility documented; then P2-1 (parallel-tool guidance) as the lever for the remaining e2e p50s."
}
```

## Iteration 3 — p2-1 — ACCEPTED

```json
{
  "iteration": 3,
  "timestamp_utc": "2026-07-09T21:45:00Z",
  "fix_id": "p2-1",
  "description": "Parallel-tool prompt guidance (NON_NEGOTIABLES rule 3: independent tools for one caller turn go in ONE LLM response) + llm_calls round-trip count made real in bench traces (register_instrumentation in the bench process).",
  "baseline_report": "20260709T211909Z.json",
  "after_report": "20260709T213408Z.json",
  "target_metric": "phone_e2e_p50_ms / web_e2e_p50_ms (submit_to_first_token on multi-tool turns)",
  "stages": {
    "eos_to_stt_ms": {
      "before_p50": 871.2284578941762,
      "after_p50": 658.8157077785581,
      "budget": 900,
      "delta_pct": -24.4
    },
    "llm_ttft_ms": {
      "before_p50": 685.116209089756,
      "after_p50": 669.5449580438435,
      "budget": 1200,
      "delta_pct": -2.3
    },
    "tts_first_byte_ms": {
      "before_p50": 0.10645785368978977,
      "after_p50": 0.09737513028085232,
      "budget": 500,
      "delta_pct": -8.5
    },
    "web_e2e_p50_ms": {
      "before_p50": 2659.64691597037,
      "after_p50": 2759.5964579377323,
      "budget": 2000,
      "delta_pct": 3.8
    },
    "phone_e2e_p50_ms": {
      "before_p50": 3170.695708831772,
      "after_p50": 2587.0603751391172,
      "budget": 2500,
      "delta_pct": -18.4
    }
  },
  "gates": {
    "lint": "pass",
    "test": "pass (521)",
    "eval": "pass (39/39, DeepSeek judge \u2014 mandatory for the prompt change)",
    "latency_overall": false
  },
  "live_runs_this_iteration": 1,
  "decision": "accepted",
  "commit": "git log: latency-loop i3 commit (p2-1)",
  "revert_commit": null,
  "notes": "Phone e2e p50 3171->2587 (-18.4%, > the 8% e2e bar); web p50 +3.8% (run noise, inside the 15% tolerance); eos_to_stt -24.4%; no PASS->FAIL crossing. Remaining: web p50 2760/2000 (+38% over), phone p50 2587/2500 (3.5% over, noise-level). NEXT HYPOTHESIS (i4): P0-4 acknowledge-before-tools is advisory-only \u2014 if the ack sentence streamed as the FIRST SentenceReady before tool round trips, web first-audio would land ~1.6s. Verify run_turn actually emits pre-tool text as SentenceReady; if swallowed until after tools, that is a real product bug and the single biggest web lever. model-pin still deferred: bot.py contested by collaborator + bench-invisible."
}
```
