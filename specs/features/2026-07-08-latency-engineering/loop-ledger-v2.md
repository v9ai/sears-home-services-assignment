# Latency Loop Ledger v2
state: running (phase 2 — i11/f6 CLAIMED 2026-07-10: validating + measuring the pre-staged ce4c842 filler-delay fix; do not start i11 elsewhere. Phase 1 closed SUCCESS: gate flipped hard, commit 85283f1)
iteration: 12
bench_runs_total: 15
judged_eval_runs_total: 8
consecutive_all_pass: 2
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

## Phase 2 charter — reopened 2026-07-10 (user "launch"; i9 notes authorized reopen "with a fresh queue")

Phase 1 hit the budget gate before exhausting its levers. Phase 2's goal is **max
possible improvement at held quality**: budgets are already hard, so the terminal
condition is DRY (2 consecutive no-accept iterations = measured maximum reached) or
the phase-2 caps — there is no gate left to flip. All phase-1 protocol rules apply
(3-run medians, paired deltas, noise-scaled accept bars, reproducible-eval rejects,
collaborator-dirt rule, revert-not-reset).

**Fresh queue (priority order; one fix-id per iteration):**

| # | fix-id | Lane | What | Notes |
|---|--------|------|------|-------|
| 1 | f5 | F | `_build_llm` code default `gpt-4o` → `gpt-4.1-mini` (`app/voice/bot.py`) | User-approved 2026-07-09; pipecat rows exist (q0-4); eval MANDATORY; update README + `test_llm_factory.py` default assert |
| 2 | f6 | F | VAD stop-secs + `FILLER_DELAY_MS` tuning on the pipecat rows | Never below 0.4 s floor; perceived row must stay PASS; false-cut guard check |
| 3 | q0-3 | Q | Eval-gate split: hermetic (mandatory) vs live (advisory, retry-once) | Phase-1 leftover; stabilizes every later accept; testing-evals delta declared in-commit |
| 4 | f1 | F | Phase-gated system prompt (contract sections injected case-file-driven) | Attacks prefill-TTFT — the i7 decomposition's dominant tail segment; eval MANDATORY |
| 5 | t1 | F | Tool-turn tail: parallel tool-call execution + per-tool timing attribution in the trace | i7 packet's frontier (5.5–10 s tails, llm_calls 2–3); scope = execution concurrency + measurement, NOT budget edits |
| 6 | f2 | F | Dynamic first-clause release (floor 40 → ≥25 chars at clause punctuation) | TTS-choppiness eval rubric must stay green |

**Phase-2 caps (second Standard tranche, same rate as phase 1):** `iteration > 18` →
STOP; `bench_runs_total >= 45` → STOP; `judged_eval_runs_total >= 18` → STOP.
Counters stay cumulative across phases.

**Open human items carried from i9 (not loop work):** web-p95 re-scope option (moot
at median — revisit only if t1 fails), `test_library_live` brittle assert,
repo-wide lint red on collaborator `evals/adaptive_driver.py`.

## Iterations

## Iteration 10 — q0-3 — ACCEPTED (this driver; f5 concurrently owned by the co-driver)

```json
{
  "iteration": 10,
  "timestamp_utc": "2026-07-10T04:55:00Z",
  "lane": "Q",
  "fix_id": "q0-3",
  "description": "Eval-gate split: `live` marker registered; test_library_live marked; Makefile eval-hermetic (-m 'not live', HARD) + eval-live (advisory, --last-failed retry-once, never fails build) with make eval = both; testing-evals gate-classes updated in-commit; 4 guard tests incl. collection-level deselection proof.",
  "baseline_report": null,
  "after_report": null,
  "target_metric": "eval-gate stability (autopsy finding #3)",
  "stages": {},
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass on surface",
    "test": "pass (596)",
    "eval": "eval-hermetic LIVE-VALIDATED: 37 passed / 2 deselected / exit 0 — first clean mandatory gate (+1 judged run, counted in header by co-driver reconciliation)",
    "latency_overall": null
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "9f561ee",
  "notes": "REORDER RATIONALE (§1.3): f5 and f6 surfaces (app/voice/bot.py, test_llm_factory.py) were the co-driver's active uncommitted work this iteration — q0-3 was the next clean-surface queue item. The chronic test_library_live stochasticity (three documented triage passes: v1-i5, i7, i8) is now advisory-lane; future mandatory-eval accepts stop paying that tax. NEXT: f6 or f1 per queue once bot.py frees up; f5 expected to land from the co-driver."
}
```

## Iteration 9 — gate-flip — ACCEPTED (terminal; loop closed SUCCESS)

```json
{
  "iteration": 9,
  "timestamp_utc": "2026-07-10T03:30:00Z",
  "lane": "terminal",
  "fix_id": "gate-flip",
  "description": "ALL-PASS MEASUREMENT #2 (runs 032030Z/032316Z/032558Z -> 20260710T032558Z-measurement.json) met §9.1; terminal flip: Makefile defaults LATENCY_GATE_HARD=1, testing-evals Decision 6 advisory->HARD, runbook §4 updated, latency-engineering plan §6 + validation gate item + deepseek-agent-llm validation #2 closed.",
  "baseline_report": "20260710T031352Z-measurement.json",
  "after_report": "20260710T032558Z-measurement.json",
  "target_metric": "gate policy",
  "stages": {
    "web_e2e": {"median_p50": 2119, "median_p95": 4717, "noise_pct": 44.7, "budget": "2800/4900", "pass": true},
    "phone_e2e": {"median_p50": 2399, "median_p95": 3686, "noise_pct": 6.3, "budget": "3200/5100", "pass": true},
    "pipecat_e2e": {"median_p50": 694, "median_p95": 1007, "noise_pct": 44.3, "budget": "3200/5100", "pass": true},
    "micro": {"eos_to_stt": 614, "llm_ttft": 726, "tts_first_byte": 0, "pass": true}
  },
  "noise_pct": {"web": 44.7, "phone": 6.3, "pipecat": 44.3},
  "paired": null,
  "gates": {"lint": "pass", "test": "pass (592)", "eval": "not required (bench/spec/Makefile gating only)", "latency_overall": true},
  "live_runs_this_iteration": 3,
  "decision": "accepted",
  "commit": "85283f1",
  "revert_commit": null,
  "notes": "LOOP CLOSED: SUCCESS. consecutive_all_pass=2 (i8 measurement + this one). Program summary v1 start -> now: web meaningful p50 3256 -> ~2020-2119 (fidelity fixes + Cartesia flip), phone 3767 -> ~2400, production pipecat path measured 694-828 (was invisible), tts row 792 -> ~0 (cache path), perceived audio 0.2-0.4ms with hard tripwires, gate advisory -> HARD. OPEN ITEMS handed to humans: (1) i7 web-p95 packet — moot at median (4717<4900) but tool-turn tails 5.5-10s remain the next frontier (options recorded in i7); (2) test_library_live brittle assert (testing-evals); (3) q0-3 eval split — unimplemented, still worthwhile; (4) repo-wide make lint red on collaborator evals/adaptive_driver.py. Loop may be reopened by resetting state to running with a fresh queue."
}
```

## Iteration 8 — f4 + ALL-PASS MEASUREMENT #1 — ACCEPTED

```json
{
  "iteration": 8,
  "timestamp_utc": "2026-07-10T03:15:00Z",
  "lane": "F",
  "fix_id": "f4",
  "description": "Re-land v1's p0-4 flush (cherry-pick a98a4f9): pre-tool acknowledgment flushed at the ToolCall boundary. Test-proven ordering; inert under gpt-4.1-mini today; protects the prose-before-tools contract on any provider change. PLUS fresh 3-run MEASUREMENT (post h2 + pcm bench fidelity).",
  "baseline_report": "20260710T020628Z-measurement.json",
  "after_report": "20260710T031352Z-measurement.json (runs 030750Z/031042Z/031352Z)",
  "target_metric": "contract protection (neutral-plus)",
  "stages": {
    "eos_to_stt_ms": {"median_p50": 592, "noise_pct": 27.1, "budget": 900, "pass": true},
    "llm_ttft_ms": {"median_p50": 740, "noise_pct": 80.7, "budget": 1200, "pass": true},
    "tts_first_byte_ms": {"median_p50": 0, "budget": 500, "pass": true},
    "web_e2e": {"median_p50": 2020, "median_p95": 4470, "noise_pct": 27.0, "budget": "2800/4900", "pass": true},
    "phone_e2e": {"median_p50": 2441, "median_p95": 3591, "noise_pct": 12.5, "budget": "3200/5100", "pass": true},
    "pipecat_e2e": {"median_p50": 760, "median_p95": 1008, "noise_pct": 37.6, "budget": "3200/5100", "pass": true}
  },
  "noise_pct": {"web": 27.0, "phone": 12.5, "pipecat": 37.6},
  "paired": null,
  "gates": {
    "lint": "pass on surface",
    "test": "pass (592)",
    "eval": "pass-with-adjudication: 37/39 twice — the documented pair (visual passes isolation §6.3; library_live brittle literal-brand assert, flagged to testing-evals since i7)",
    "latency_overall": true
  },
  "live_runs_this_iteration": 3,
  "decision": "accepted",
  "commit": "3b6bc88",
  "revert_commit": null,
  "notes": "ALL-PASS MEASUREMENT #1 (first in project history): every stage's 3-run median green — web 2020/4470 (h2 Cartesia cut both p50 AND tail; i7's mp3->pcm bench fidelity fix made it visible), phone 2441/3591, pipecat 760/1008. Run 3 individually FAILed on one phone p95 outlier (5963, single hung call) — absorbed by the median rule as designed. consecutive_all_pass=1. The i7 web-p95 packet MAY be moot (4470<4900 at median) — keep it open one more measurement. NEXT (i9): MEASUREMENT #2; if all medians PASS again -> terminal gate-flip (§9.1)."
}
```

## Iteration 7 — h2 — ACCEPTED (+ new H packet: web-meaningful-p95 re-scope, awaiting-human)

```json
{
  "iteration": 7,
  "timestamp_utc": "2026-07-10T02:50:00Z",
  "lane": "H",
  "fix_id": "h2",
  "description": "Web TTS default flips to Cartesia for pcm (user decision 2026-07-10; f3 A/B condition met: 223ms vs 696ms). Escape hatch WEB_TTS_PROVIDER=openai; mp3 stays OpenAI. Companion bench-fidelity fix: web bench first-audio synth now pcm like production (the mp3 default hid the flip and inflated the row).",
  "baseline_report": "20260710T020628Z-measurement.json",
  "after_report": "20260710T024642Z.json (single post-fix run; fresh MEASUREMENT owed next iteration)",
  "target_metric": "web first_token->first_audio segment",
  "stages": {},
  "noise_pct": null,
  "paired": {"web_tts_now_visible": "first_token_to_first_sentence 69-643ms post-flip (was the ~1s OpenAI mp3 leg)"},
  "gates": {
    "lint": "pass on surface",
    "test": "pass (591)",
    "eval": "pass-with-adjudication: 37/39 twice; visual flake passes isolation (§6.3); test_library_live is a brittle literal-brand assert on live LLM output failing ~50% regardless of tree (no TTS surface, predates h2, passed/failed on both provider settings across 5 runs) — flagged to testing-evals, NOT a regression",
    "latency_overall": false
  },
  "live_runs_this_iteration": 2,
  "decision": "accepted",
  "commit": "5663a57",
  "revert_commit": null,
  "notes": "DECOMPOSITION (post-flip run 024642Z, slowest web turns): submit_to_first_token 5.2-9.3s with llm_calls 2-3 — the web p95 tail is TOOL ROUND TRIPS + tool execution before any prose, NOT TTS (now 69-643ms token->sentence). Phone 2346 PASS, pipecat 740 PASS. NEW H PACKET (awaiting-human): web_meaningful_p95 4900 cannot absorb a 2-3-round tool turn (measured 5611-10161 tails even with fast TTS); options: (a) re-scope web meaningful p95 to ~6500 (measured tail + margin), (b) accept f4 prose-before-tools re-land as the only code lever (model-dependent, was inert under gpt-4.1-mini), (c) keep FAILing and treat as the roadmap's next optimization frontier. NEXT (i8): f4 re-land (cheap, correct, protects the contract) + fresh 3-run MEASUREMENT; the p95 packet stays open for the user."
}
```

## Iteration 6 — f3 (+ MEASUREMENT under h1 gating) — ACCEPTED

```json
{
  "iteration": 6,
  "timestamp_utc": "2026-07-10T02:35:00Z",
  "lane": "F",
  "fix_id": "f3",
  "description": "Web TTS Cartesia adapter (WEB_TTS_PROVIDER=cartesia, pcm24k via Cartesia SSE, mp3 falls through to OpenAI) + live paired A/B. Default UNCHANGED (openai) — the flip is h2. Also: 3-run MEASUREMENT under the h1 split (runs 015729Z/020323Z/020628Z -> 20260710T020628Z-measurement.json).",
  "baseline_report": "20260710T014427Z-measurement.json",
  "after_report": "20260710T020628Z-measurement.json",
  "target_metric": "web dynamic-sentence TTS TTFB (A/B evidence for h2)",
  "stages": {
    "eos_to_stt_ms": {"median_p50": 691, "noise_pct": 9.0, "budget": 900, "pass": true},
    "llm_ttft_ms": {"median_p50": 710, "noise_pct": 37.9, "budget": 1200, "pass": true},
    "tts_first_byte_ms": {"median_p50": 0, "budget": 500, "pass": true},
    "web_e2e": {"median_p50": 2496, "median_p95": 5479, "noise_pct": 38.0, "budget": "2800/4900 meaningful", "pass": false},
    "phone_e2e": {"median_p50": 2591, "median_p95": 3453, "noise_pct": 17.3, "budget": "3200/5100 meaningful", "pass": true},
    "pipecat_e2e": {"median_p50": 704, "median_p95": 1008, "noise_pct": 43.1, "budget": "3200/5100 meaningful", "pass": true}
  },
  "noise_pct": {"web": 38.0, "phone": 17.3, "pipecat": 43.1},
  "paired": {"ab_web_tts_ttfb_p50_ms": {"openai_pcm": 696, "cartesia_pcm": 223, "openai_mp3": 999, "cartesia_mp3": "unsupported (SSE 400)"}},
  "gates": {
    "lint": "pass on surface",
    "test": "pass (589 after test fix; full suite green)",
    "eval": "pass-with-flake-evidence: 37/39 full run; the 2 failures (visual_post_upload_incorporation, test_library_live) are the v1-i5 documented flakes and both PASSED on the §6.3 isolation retry — non-reproducible, not regressions",
    "latency_overall": false
  },
  "live_runs_this_iteration": 2,
  "decision": "accepted",
  "commit": "1c1d835",
  "revert_commit": null,
  "notes": "MEASUREMENT under h1: everything PASSES except web median p95 5479 vs 4900 — reproducible across all 3 runs (5479/5253/5489), NOT noise: the web scenario matrix has consistent ~5.5s multi-tool turns. A/B CONFIRMS h2's condition decisively: Cartesia pcm 223ms vs OpenAI 696ms (3.1x, -473ms/sentence — applied to the tail turns this should close most of the 579ms p95 gap). NEXT (i7): h2 — flip WEB_TTS_PROVIDER default to cartesia (one-line + .env.example + README note), eval mandatory, then MEASUREMENT: if all medians PASS that is all-PASS #1 of 2 for the gate flip. q0-3 (eval split) rising in priority — the flaky pair has now cost two documented triage passes."
}
```

## Iteration 5 — h1 — ACCEPTED (user-authorized budget split implemented)

```json
{
  "iteration": 5,
  "timestamp_utc": "2026-07-10T02:00:00Z",
  "lane": "H",
  "fix_id": "h1",
  "description": "Perceived/meaningful budget split per user decision 2026-07-10: *_e2e_* re-scoped as first-PERCEIVED-audio hard tripwires (numbers unchanged); new meaningful-reply budgets web 2800/4900, phone 3200/5100 (measured floors 2565/2585 + margin). Bench gates e2e fields on meaningful + perceived rows on perceived; pipecat row gates as meaningful. budgets.py + specs/latency/budgets.md + sync tests + technical-design rows in one commit.",
  "baseline_report": "20260710T014427Z-measurement.json",
  "after_report": "20260710T015729Z.json (single validation run)",
  "target_metric": "gating semantics (neutral-plus; no product diff)",
  "stages": {},
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass on surface",
    "test": "pass (577)",
    "eval": "skipped (justified: budget/bench/spec semantics only — no prompt, tool, or agent behavior change)",
    "latency_overall": false
  },
  "live_runs_this_iteration": 1,
  "decision": "accepted",
  "commit": "7a62064",
  "revert_commit": null,
  "notes": "First run under the split: micro all PASS, phone e2e PASS (2590<3200, p95 3453<5100), pipecat PASS (703ms p50), perceived 0.2-0.4ms PASS. Web FAIL only on p95 tail 5479>4900 from ONE slow turn (p95=max at N=5 turns; the same turn failed old gating harder at 3500). No fix-caused PASS->FAIL crossing -> neutral-plus accept. NEXT: a full 3-run MEASUREMENT — if its medians all PASS this is measurement 1 of the 2 needed for the §9 gate flip; the web p95 tail (slow multi-tool turns) is the remaining F-lane target if it recurs (q0-3 eval split before any prompt-touching fix)."
}
```

## Iteration 4 — q0-5 + baseline MEASUREMENT — ACCEPTED

```json
{
  "iteration": 4,
  "timestamp_utc": "2026-07-10T01:50:00Z",
  "lane": "Q",
  "fix_id": "q0-5",
  "description": "Perceived-audio visibility rows: web+phone bench turns record first_perceived_audio_ms (cached-filler first chunk) + first_meaningful_audio_ms; summaries surface p50_first_perceived_audio_ms; gating untouched. PLUS the first full 3-run baseline MEASUREMENT (all channels incl. pipecat).",
  "baseline_report": null,
  "after_report": "20260710T014427Z-measurement.json (runs 013835Z/014135Z/014427Z)",
  "target_metric": "first_perceived_audio_ms (new visibility)",
  "stages": {
    "eos_to_stt_ms": {"median_p50": 719, "noise_pct": 49.1, "budget": 900, "pass": true},
    "llm_ttft_ms": {"median_p50": 670, "noise_pct": 7.4, "budget": 1200, "pass": true},
    "tts_first_byte_ms": {"median_p50": 0, "noise_pct": 77.5, "budget": 500, "pass": true},
    "web_e2e": {"median_p50": 2565, "median_p95": 4632, "noise_pct": 26.5, "budget": "2000/3500", "pass": false},
    "phone_e2e": {"median_p50": 2585, "median_p95": 3849, "noise_pct": 14.3, "budget": "2500/4000", "pass": false},
    "pipecat_e2e": {"median_p50": 828, "median_p95": 1008, "noise_pct": 23.5, "budget": "2500/4000", "pass": true}
  },
  "noise_pct": {"web": 26.5, "phone": 14.3, "pipecat": 23.5},
  "paired": null,
  "gates": {
    "lint": "pass on surface (repo-wide: collaborator adaptive_driver.py still red)",
    "test": "pass (575)",
    "eval": "skipped (justified: measurement-only diff in bench/driver latency-collection code; no prompt/tool/agent behavior)",
    "latency_overall": false
  },
  "live_runs_this_iteration": 3,
  "decision": "accepted",
  "commit": "e028e80",
  "revert_commit": null,
  "notes": "H1 EVIDENCE PACKAGE COMPLETE: perceived-audio p50 0.2-0.4ms on the warm cache (caller hears filler instantly); production pipecat path median 828ms p50 / 1008ms p95 (3x headroom, stable); legacy floors web 2565 / phone 2585. The user-approved meaningful budgets (web 2800 / phone 3200 p50) sit above the measured floors — the approved numbers are achievable as-is, no re-derivation needed; p95s from ratios: web 4900, phone 5100 (both above measured 4632/3849). NEXT (i5): implement h1 — the authorized budget split (perceived hard budgets + meaningful-reply budgets in app/latency/budgets.py + specs/latency/budgets.md + sync tests + bench gating on the new semantics) citing ledger decision #1."
}
```

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

## Iteration 10 — f5 — ACCEPTED (pre-staged diff validated)

```json
{
  "iteration": 10,
  "timestamp_utc": "2026-07-10T05:20:00Z",
  "lane": "F",
  "fix_id": "f5",
  "description": "VOICE_LLM_MODEL code default gpt-4o -> gpt-4.1-mini (_build_llm), README + test_llm_factory default assert. Diff was PRE-STAGED by the reopen-prep commit 829bd2a (anomaly noted: fix landed without its validation/record); this iteration supplied the missing validation and record.",
  "baseline_report": "20260710T032558Z-measurement.json (reused: <24h, runtime-identical \u2014 .env pins VOICE_LLM_MODEL=gpt-4.1-mini, so the default change is masked live)",
  "after_report": null,
  "target_metric": "code-default alignment (neutral-class under the .env pin; user-approved 2026-07-09)",
  "stages": null,
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass",
    "test": "pass (592)",
    "eval": "pass \u2014 exit 0 under the NEW q0-3 split (eval-hermetic hard lane green, eval-live advisory 1 passed); q0-3 itself landed via collaborator commits, so queue item #3 is DONE without a loop iteration",
    "latency_overall": true
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "829bd2a (carrying) + i10 claim/record commits",
  "revert_commit": null,
  "notes": "Neutral accept: no measurement owed (runtime-identical under the env pin; the default matters for env-less deploys). Executor-coordination note: claimed i10 in the ledger header BEFORE validating to serialize against the concurrent session \u2014 recommend future pre-staged fixes carry their own ledger claim. Queue after this: f6 (next), q0-3 DONE (collaborator), then f1, t1, f2."
}
```

## Iteration 11 — f6 — ACCEPTED

```json
{
  "iteration": 11,
  "timestamp_utc": "2026-07-10T05:45:00Z",
  "lane": "F",
  "fix_id": "f6",
  "description": "Filler default delay derives from its own budget: _filler_delay_default_s hardcoded 1000ms -> FILLER_AFTER_EOS_MS (800ms). With FILLER_DELAY_MS unset, every filler fired 200ms past the perceived-latency budget it exists to meet. Env override preserved; regression test pins default == budget.",
  "baseline_report": "n/a (neutral-class: live-knob coherence fix; filler stripped from hermetic latency tests, pipecat row measures the meaningful reply)",
  "after_report": null,
  "target_metric": "perceived-audio budget coherence",
  "stages": null,
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass",
    "test": "pass (614; 4 stutter-loop analyzer tests failed in the full run from parallel churn, 17/17 green in isolation per SS6.2 \u2014 files owned by the concurrent stutter loop, untouched by this diff)",
    "eval": "pass (q0-3 split: hermetic 37 green, live 2 green)",
    "latency_overall": true
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "latency-loop2 i11 commit (f6)",
  "revert_commit": null,
  "notes": "f6's VAD half recorded as NO-OP: .env already runs the 0.4s floor; VAD stop-secs is bench-invisible (pipecat bench injects UserStoppedSpeakingFrame directly); and moving VAD_STOP_SECS_DEFAULT 0.5->0.4 means editing budgets.py \u2014 SS5-forbidden without a human decision. OPEN HUMAN ITEM: consider aligning VAD_STOP_SECS_DEFAULT to the .env-proven 0.4 floor in budgets.py. NEXT: f1 phase-gated system prompt (real latency fix; needs 3-run candidate measurement + paired compare + mandatory eval)."
}
```

## Iteration 12 — t1 — ACCEPTED

```json
{
  "iteration": 12,
  "timestamp_utc": "2026-07-10T06:10:00Z",
  "lane": "F",
  "fix_id": "t1",
  "description": "Per-tool wall attribution: ToolCall->ToolCallResult event pairs (tool_id-keyed, parallel-safe) -> trace extras tool_ms (name:ms) + tool_ms_total. Decomposes the i7 tool-turn tails into tool execution vs LLM round trips.",
  "baseline_report": "n/a (neutral-class measurement diff)",
  "after_report": null,
  "target_metric": "tail attributability",
  "stages": null,
  "noise_pct": null,
  "paired": null,
  "gates": {
    "lint": "pass",
    "test": "pass (626)",
    "eval": "pass under SS6.3: hermetic run had 2 near-cutoff failures (visual_post_upload photo-findings 0.6/0.8, scheduling_slot_conflict) \u2014 BOTH passed on the reproducibility retry; t1 is measurement-only and cannot alter conversation content. First validation battery externally killed after suite green; eval re-run standalone.",
    "latency_overall": true
  },
  "live_runs_this_iteration": 0,
  "decision": "accepted",
  "commit": "2bdd3bc",
  "revert_commit": null,
  "notes": "t1 concurrency half = recorded NO-OP with evidence: FunctionAgent.allow_parallel_tool_calls defaults True (OpenAI receives parallel_tool_calls=true) and the workflow's call_tool @step already executes concurrent ToolCall events; emission is prompt-directed since i3/p2-1. OPEN ITEM (testing-evals): hermetic-lane flake rate climbing (2/37 this run, all near the 0.8 G-Eval cutoff; photo-findings criterion 3 'mentioned again after the turn' is ambiguous) \u2014 rubric calibration owed."
}
```

## Queue disposition — f1 — BLOCKED (low yield)

```json
{
  "iteration": "12b (queue disposition, no diff)",
  "timestamp_utc": "2026-07-10T06:12:00Z",
  "lane": "F",
  "fix_id": "f1",
  "description": "Phase-gated system prompt \u2014 BLOCKED (low yield, quantified before spending).",
  "decision": "blocked",
  "notes": "Quantified: SCHEDULING_CONTRACT+IMAGE_UPLOAD_CONTRACT = 2499 chars ~ 624 tok = 48% of the 1294-tok empty-case prompt \u2014 BUT eval-safe gating (scheduling offer rules must be present whenever appliance/symptoms exist; photo spell-back can trigger in turn 1) limits the drop to empty-case rounds ~ the first LLM round of turn 1 only. Expected saving ~30-60ms on one round per call; cannot clear the SS7 bar and not worth 3 bench runs. RETRY HYPOTHESIS: revisit if a mid-turn prompt-refresh seam lands on the web channel (voice already refreshes via SystemPromptRefreshProcessor), which would let contracts join the prompt the moment their case-file trigger fires."
}
```
