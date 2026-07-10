# Latency Loop Ledger v2
state: running
iteration: 3
bench_runs_total: 1
judged_eval_runs_total: 0
consecutive_all_pass: 0
lane_no_accepts: {"Q": 0, "F": 0, "H": 0}

Durable state for the `/latency-maximize` loop (protocol:
`loop-v2-protocol.md`, skill `.claude/skills/latency-maximize/`). v1 history and
autopsy: `loop-ledger.md` (stopped exhausted 2026-07-09; every micro stage PASS,
e2e floor-bound, ±40 % N=5 variance, bench Pipecat-blind).

## Human decisions — recorded 2026-07-10 (user, via AskUserQuestion; supersede the
## corresponding H-lane "awaiting-human" packets — the loop may APPLY these, citing
## this section, instead of writing packets for them)

1. **h1 RESOLVED — budget semantics: perceived-audio split.** The e2e first-audio
   budgets are redefined as **first PERCEIVED audio** (cached greeting/filler counts;
   hard budget, expected ~0 ms on the cache path — reuse `FILLER_AFTER_EOS_MS`-class
   numbers), and a NEW **meaningful-reply** budget is added at the measured floor +
   margin: **web p50 2800 ms, phone p50 3200 ms** (user-approved numbers). p95s: pin
   from the current p95/p50 ratios (web ×1.75 → 4900, phone ×1.6 → 5100) and record
   in the implementing iteration's entry. Implementation = the canonical two-file
   procedure (`app/latency/budgets.py` + `specs/latency/budgets.md` together; sync
   tests updated in the same commit) — this is the ONE authorized budget edit under
   protocol §5, by this decision. Requires q0-5's perceived-vs-meaningful metric so
   both rows are measured, not asserted.
2. **h2 RESOLVED (conditional) — web TTS default flips to Cartesia** IF f3's paired
   A/B confirms the TTFB gain (expected ~½ of OpenAI's 0.8–1.0 s) AND eval quality
   gates stay green. No further packet needed; the flip lands as a normal F-lane fix
   citing this decision, with the A/B table in its ledger entry.
3. **q0-4 CONFIRMED — Pipecat-native bench is approved and prioritized** (with the
   variance protocol §2) ahead of any voice-knob fix; f5 (`model-pin`, already
   user-approved 2026-07-09 conditional on evals) and f6 (VAD/filler) remain gated
   on it.

## Iterations

## Iteration 3 — q0-4 — ACCEPTED

```json
{
  "iteration": 3,
  "timestamp_utc": "2026-07-10T02:40:00Z",
  "lane": "Q",
  "fix_id": "q0-4",
  "description": "Pipecat-native e2e bench (scripts/latency_pipecat.py): production conversation pipeline + real env-selected LLM/TTS, timed by VoiceMetricsObserver; scripted STT; optional end_to_end.pipecat report section gated on the phone envelope; measurement folding + render extended; missing keys FAIL loudly. 12 hermetic tests.",
  "baseline_report": null,
  "after_report": "live smoke only (1 scenario, not a full run)",
  "target_metric": "pipecat_eos_to_first_audio_ms (new observability)",
  "stages": {},
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass on the q0-4 surface (repo-wide unchanged: collaborator evals/adaptive_driver.py still red)",
    "test": "pass (572, zero failures)",
    "eval": "skipped (justified: pure-harness diff — bench code; app/voice/bot.py is IMPORTED, not modified)",
    "latency_overall": null
  },
  "live_runs_this_iteration": 1,
  "decision": "accepted",
  "commit": "1e99733",
  "revert_commit": null,
  "notes": "HEADLINE: live smoke of the REAL phone path (gpt-4.1-mini + Cartesia via .env) = 1024 ms eos->first-audio — comfortably UNDER the 2500 ms phone p50 budget. v1's floor-bound verdict was about the LEGACY bench primitives (OpenAI TTS + full-prefill run_turn), not the production pipeline. Implications: (a) f5 model-pin becomes code-default alignment with live confirmation now possible; (b) the h1 meaningful-reply budget numbers (web 2800/phone 3200) should be re-derived from a full pipecat MEASUREMENT before landing — the 3200 phone number may be far too loose for the real path; flag this in the h1-implementing iteration. bot.py was import-only (collaborator-dirty, §1.3 respected). NEXT: full 3-run MEASUREMENT (--repeat 3) to baseline all channels including pipecat rows under the new statistics, then f-lane work off that baseline."
}
```

## Iteration 2 — q0-2 — ACCEPTED

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-10T02:20:00Z",
  "lane": "Q",
  "fix_id": "q0-2",
  "description": "latency_bench --repeat N: one MEASUREMENT = N runs folded into a schema-v3 envelope ({ts}-measurement.json) — median p50 + noise_pct per stage/channel, verdicts on medians (p50 AND p95 for e2e), no-data run fails the channel, gate-hard exit follows the measurement verdict. 10 offline tests.",
  "baseline_report": null,
  "after_report": null,
  "target_metric": null,
  "stages": {},
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass on the q0-2 surface (repo-wide make lint still FAILs on collaborator evals/adaptive_driver.py — unchanged from i1)",
    "test": "pass (560, zero failures)",
    "eval": "skipped (justified: pure-harness diff — bench/comparator measurement code only)",
    "latency_overall": null
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "21cb1d3",
  "revert_commit": null,
  "notes": "Makefile latency-3 variant SKIPPED (Makefile collaborator-dirty at iteration start — §1.3); invoke as `python scripts/latency_bench.py --repeat 3`; add the make target later when the file frees up. Collaborator dirt at commit: Makefile, app/voice/bot.py, roadmap, protocol, test_bargein_guard, booking-quality untracked set. With q0-1 (paired deltas) + q0-2 (median measurements) the v2 statistical accept basis is COMPLETE — latency-class fixes are now acceptable. NEXT: q0-3 (eval-gate hermetic/live split) or q0-4 (Pipecat-native bench) — q0-4 preferred if surfaces stay clean, it unlocks f5/f6 and the user-confirmed decision #3."
}
```

## Iteration 1 — q0-1 — ACCEPTED

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-10T01:30:00Z",
  "lane": "Q",
  "fix_id": "q0-1",
  "description": "latency_compare.py --paired: record-matched (scenario_id, turn_index) median-of-per-pair-deltas + improving/regressing sign counts, per channel e2e metric and per segment field; unmatched/None records skipped and counted. 7 offline tests.",
  "baseline_report": null,
  "after_report": null,
  "target_metric": null,
  "stages": {},
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass on the q0-1 surface (repo-wide make lint FAILs on collaborator in-flight evals/adaptive_driver.py — F401 + E501, untouched by this diff; v1 i2 precedent applied)",
    "test": "pass (548; 2 order-dependent failures in collaborator UNTRACKED tests/test_booking_quality_policy.py passed 20/20 in isolation — §6.2 rule, does not block)",
    "eval": "skipped (justified: pure-harness diff — comparator + its tests only)",
    "latency_overall": null
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "5d283f9",
  "revert_commit": null,
  "notes": "Neutral lane-Q fix; unblocks §2's paired-delta accept basis for every later latency-class fix. Collaborator dirt at commit time: app/voice/bot.py, tests/voice/test_bargein_guard.py, loop-v2-protocol.md (their §10 pre-resolution of h1/h2 — consistent with this ledger's Human-decisions section), untracked booking-quality files. NEXT: q0-2 (make latency --repeat 3 = one MEASUREMENT, medians + noise_pct, schema v3)."
}
```
