# Latency Loop Ledger v2
state: running
iteration: 1
bench_runs_total: 0
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
