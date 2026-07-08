# Latency Engineering — Plan

Measure first, fix second, flip the gate last. Every fix group ends with a
`make latency` rerun archived to `data/latency/`.

## 0. Root-cause measurement (DONE 2026-07-08 — see requirements § RCA)
- [x] Micro-benchmarks run (N=3–5): LLM TTFT 801 ms p50 · TTS first-byte 573 ms /
      full-sentence 1324 ms p50 · STT 588 ms p50 · network TTFB dev↔OpenAI ~0.93 s vs
      CF worker 0.4 s.
- [x] Instrumented production turn (web shape): first sentence 3.43 s, first audio
      4.68 s, **serialized TTS = 11.34 s of 15.04 s (75%)** — the dominant root cause.
- [x] Evidence table + ranked verdict recorded in requirements § Root-cause analysis.

## 1. Instrumentation completion
- [ ] Phone: land telephony plan group 5's per-turn trace fields (already spec'd
      there). Web: equivalent timings in `app/ws/routes.py`
      (submit→first-token/first-sentence/first-audio). One shared trace-record shape.

## 2. Bench harness
- [ ] `scripts/latency_bench.py` + `make latency`: micro-benchmarks (LLM TTFT, STT,
      TTS TTFB; N=5, p50/p95, key-gated skip-loud) + end-to-end scenario runs via the
      live driver + `data/latency/{ts}.json` report with budget PASS/FAIL columns.
- [ ] Baseline run archived (the "before" table).

## 3. P0 fixes — **APPLIED 2026-07-09 (commit c93bb25); measured**
- [x] **P0-3 parallel TTS pipeline** — `app/agent/tts_pipeline.py` (lookahead 2),
      wired into both channels; ordering + overlap + backpressure + overhead-floor
      guards in `tests/latency/`.
- [x] **P0-4 first-prose-before-tools** + **O8 ≤3-sentence voice cap** — PERSONA
      lines + static prompt asserts (advisory to the model; O8 observed cutting
      7→4-5 sentences in measurement runs, not always honored).
- [x] P0-1 TTS cache completed: cache-first both channels + **boot-time prewarm**
      (startup hook) so no caller pays the cold synth; cache-hit + stale-hash guards.
- [x] P0-2 filler at end-of-speech, launched **concurrent** with the agent turn
      (inline await measurably delayed run_turn — caught in the after-measurement
      and fixed same day).
- [x] AFTER (same scenario as baseline): **filler audio 0.00 s from cache** (was
      4.68 s of dead air), turn total 11.7 s vs 15.0 s baseline. `make latency`
      harness (groups 1–2) still owed for the formal p50/p95 report.

## 4. P1 fixes
- [x] P1-1 async IO — persist + recording writes fire-and-forget in both channels
      (Neon RTT grounded at 120 ms; wav-wrapped recordings); off-critical-path guard
      in `tests/latency/`. **APPLIED 2026-07-09 (c93bb25).**
- [ ] P1-2 prompt slimming (compact case-file JSON; conditional knowledge vocab);
      token counts logged before/after.
- [x] P1-3 first-clause chunking (≥40 chars, first emission only) + unit.
      **APPLIED 2026-07-09 (c93bb25).**
- [ ] `make latency` rerun; expect first_token_to_first_sentence_ms ≤ 800.

## 4b. Regression-proof tests — **APPLIED 2026-07-09 (c93bb25)**
- [x] `tests/latency/` suite: parallelism, backpressure, cache-hit, filler-timing,
      async-IO, first-clause, and the **pipeline-overhead floor** guard — all
      fake-based, zero live APIs, permanent in `make test`.
- [ ] Live tripwires wired into `make latency`: serialization ratio ≤ 0.7 ·
      P0-4 prose-before-tools sampling.
- [ ] Every test lands in the SAME commit as (or before) its fix — a fix without its
      guard doesn't tick.

## 4c. Deep-RCA fixes (round 2, unimplemented)
- [ ] O8 voice-reply length cap (prompt; Conversation Completeness must not regress).
- [ ] O9 web pcm/wav streaming + O12 gapless WebAudio queue (measured 270 ms/sentence
      mp3 tax + per-blob decode gaps) — one coordinated web+ws change.
- [x] O10 `/debug/latency-probe` (flag-gated, `LATENCY_PROBE_ENABLED`) shipped —
      hosted RTT column still to be captured post-deploy. **APPLIED 2026-07-09.**
- [x] O11 keep-warm: `[triggers] crons = */10` + `scheduled()` handler pinging the
      container `/healthz`. **APPLIED 2026-07-09.**

## 5. P2 decision gates
- [ ] P2-1 parallel-tool prompt guidance + round-trip count in the trace.
- [ ] P2-2 provider A/B table (DeepSeek vs openai fallback) → recorded decision on
      the demo-day default.
- [ ] P2-3 tunnel: ngrok region interim; hosted CF path when Phase 4's deploy lands.
- [ ] P3-1 VAD knob + false-cut guard (only if L2 shows up in the report).

## 6. Flip the gate
- [ ] Two consecutive all-PASS `make latency` runs → latency gate advisory→hard
      (evals), updating testing-evals Decision 6 and closing deepseek-agent-llm
      validation #2 with the measured table.

## Integration deltas (lead applies — owned files)
- `app/ws/routes.py` + `app/phone/real_agent.py`/`bridge.py`: cache-first playback,
  eos-filler, async persist hooks (voice-core/telephony owners).
- `app/agent/prompts.py`/`pipeline.py`: slimming + first-clause (voice-core owner).
- `Makefile`: `latency` row. `.gitignore`: `data/latency/`, `data/tts_cache/`.
