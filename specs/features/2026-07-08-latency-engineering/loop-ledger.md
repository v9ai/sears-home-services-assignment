# Latency Loop Ledger
state: running
iteration: 1
live_runs_total: 2
consecutive_all_pass: 0
consecutive_no_accept: 0
branch: latency-loop

Durable state for the `/latency-iterate` loop (`.claude/skills/latency-iterate/`).
`data/` is gitignored, so report summaries live here. Counters above are the §1/§8
preconditions' source of truth.

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
