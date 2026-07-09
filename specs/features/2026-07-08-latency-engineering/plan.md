# Latency Engineering — Plan

Measure first, fix second, flip the gate last. Every fix group ends with a
`make latency` rerun archived to `data/latency/`.

> **Phone channel re-homed to Pipecat (2026-07-09).** The phone media loop this plan
> optimized (`app/phone/{vad,stt,bridge,real_agent}.py`) was replaced by a Pipecat pipeline
> (`app/voice/`) — see `specs/features/2026-07-09-pipecat-voice-port/`. The web-channel
> fixes below (`app/ws`, `app/agent/*`) stand as applied; the phone halves of the TTS,
> framing, barge-in, and persist work are **superseded** (Pipecat owns them) and annotated
> as such. The applied-commit history is kept as the record. `scripts/latency_bench.py`'s
> phone bench now measures the LLM+TTS stack directly (bridge dropped); live phone latency
> is captured by Pipecat's per-call metrics (`PipelineParams(enable_metrics=True)`).

## 0. Root-cause measurement (DONE 2026-07-08 — see requirements § RCA)
- [x] Micro-benchmarks run (N=3–5): LLM TTFT 801 ms p50 · TTS first-byte 573 ms /
      full-sentence 1324 ms p50 · STT 588 ms p50 · network TTFB dev↔OpenAI ~0.93 s vs
      CF worker 0.4 s.
- [x] Instrumented production turn (web shape): first sentence 3.43 s, first audio
      4.68 s, **serialized TTS = 11.34 s of 15.04 s (75%)** — the dominant root cause.
- [x] Evidence table + ranked verdict recorded in requirements § Root-cause analysis.

## 1. Instrumentation completion
- [ ] Web: timings in `app/ws/routes.py`
      (submit→first-token/first-sentence/first-audio). One shared trace-record shape.
- [x] Phone: **superseded by Pipecat (2026-07-09)** — per-turn timing now comes from
      Pipecat's per-call metrics (`PipelineParams(enable_metrics=True)` in
      `app/voice/bot.py`), not app-emitted trace fields; the old telephony group-5 phone
      trace is retired with `app/phone/real_agent.py`.

## 2. Bench harness
- [ ] `scripts/latency_bench.py` + `make latency`: micro-benchmarks (LLM TTFT, STT,
      TTS TTFB; N=5, p50/p95, key-gated skip-loud) + end-to-end scenario runs via the
      live driver + `data/latency/{ts}.json` report with budget PASS/FAIL columns.
      *(Updated 2026-07-09: `bench_e2e_phone` dropped the deleted `TwilioMediaBridge` and
      now measures the provider-independent LLM+TTS stack directly — live per-call phone
      latency comes from Pipecat metrics, per `scripts/latency_bench.py:bench_e2e_phone`.)*
- [ ] Baseline run archived (the "before" table).

## 3. P0 fixes — **APPLIED 2026-07-09 (commit c93bb25); measured**
> Applied to both channels at the time; the **phone** halves were **superseded 2026-07-09**
> by the Pipecat port (`app/voice/`) — Pipecat streams TTS natively (no per-sentence
> pipeline), so P0-1/P0-2/P0-3 now apply only to the **web** channel. Kept as record.
- [x] **P0-3 parallel TTS pipeline** — `app/agent/tts_pipeline.py` (lookahead 2);
      ordering + overlap + backpressure + overhead-floor guards in `tests/latency/`.
      **Web only** now — the phone `_say` loop and `app/phone/real_agent.py` were deleted;
      `app/agent/tts_pipeline.py` is no longer on the phone path (Pipecat streams TTS).
- [x] **P0-4 first-prose-before-tools** + **O8 ≤3-sentence voice cap** — PERSONA
      lines + static prompt asserts (advisory to the model; O8 observed cutting
      7→4-5 sentences in measurement runs, not always honored). The same
      `build_system_prompt` is reused verbatim by the Pipecat phone pipeline.
- [x] P0-1 TTS cache completed: cache-first (web) + **boot-time prewarm**
      (startup hook) so no caller pays the cold synth; cache-hit + stale-hash guards.
      *(Phone: superseded — Pipecat's greeting is a constant `TTSSpeakFrame(GREETING)`
      queued on connect with no LLM round trip; no app-side TTS cache on the phone path.)*
- [x] P0-2 filler at end-of-speech, launched **concurrent** with the agent turn
      (inline await measurably delayed run_turn — caught in the after-measurement
      and fixed same day). *(Web only — Pipecat streams the first token to TTS with native
      barge-in, so the phone channel has no dead-air window to mask.)*
- [x] AFTER (same scenario as baseline): **filler audio 0.00 s from cache** (was
      4.68 s of dead air), turn total 11.7 s vs 15.0 s baseline. `make latency`
      harness (groups 1–2) still owed for the formal p50/p95 report.

## 4. P1 fixes
- [x] P1-1 async IO — persist + recording writes fire-and-forget (Neon RTT grounded at
      120 ms; wav-wrapped recordings); off-critical-path guard in `tests/latency/`.
      **APPLIED 2026-07-09 (c93bb25).** *(Web only after the Pipecat port — Pipecat owns
      per-call session/memory on the phone path and the old inline `app/phone/real_agent.py`
      persist is gone; cross-call phone persistence deferred, pipecat-voice-port § Not
      included.)*
- [x] P1-2 prompt slimming — **APPLIED 2026-07-09** (compact case-file JSON, no
      `indent=2`; conditional knowledge vocab was already in place). Retagged a cost
      fix, not latency, per round-3 RCA (TTFT payload-insensitive at this scale) —
      char-count savings logged at DEBUG via `app.agent.prompts`; static compact-JSON
      assert added to `tests/latency/test_channel_guards.py`.
- [x] P1-3 first-clause chunking (≥40 chars, first emission only) + unit.
      **APPLIED 2026-07-09 (c93bb25).** *(Web only — the phone channel no longer chunks in
      app code; Pipecat's LLM→TTS seam streams tokens directly.)*
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
- [x] O9 + O12 **COMPLETE 2026-07-09**: server emits `pcm24k` (additive AudioFrame
      `format` field, mp3 legacy preserved); client `PcmPlaybackQueue` plays gapless
      via one shared 24 kHz AudioContext with chained `source.start(startAt)`
      scheduling (zero inter-sentence decode gaps), autoplay unlocked on first send,
      barge-in stop-and-clear; `tsc` + `next build` green; both Workers redeployed
      (app 756c92cf, web dda2a4c6) and hosted smoke PASS.
- [x] O10 `/debug/latency-probe` (flag-gated, `LATENCY_PROBE_ENABLED`) shipped —
      hosted RTT column still to be captured post-deploy. **APPLIED 2026-07-09.**
- [x] O11 keep-warm: `[triggers] crons = */10` + `scheduled()` handler pinging the
      container `/healthz`. **APPLIED 2026-07-09.**

## 5. P2 decision gates
- [ ] P2-1 parallel-tool prompt guidance + round-trip count in the trace.
- [ ] P2-2 provider A/B table (DeepSeek vs openai fallback) → recorded decision on
      the demo-day default.
- [ ] P2-3 tunnel: ngrok region interim; hosted CF path when Phase 4's deploy lands.
- [ ] P3-1 VAD tuning + false-cut guard (only if L2 shows up in the report) — on the phone
      channel this is now the Silero analyzer's params inside Pipecat
      (`VADProcessor(SileroVADAnalyzer())`), not the deleted RMS `TurnSegmenter` knob.

## 6. Flip the gate
- [ ] Two consecutive all-PASS `make latency` runs → latency gate advisory→hard
      (evals), updating testing-evals Decision 6 and closing deepseek-agent-llm
      validation #2 with the measured table.

## Integration deltas (lead applies — owned files)
- `app/ws/routes.py`: cache-first playback, eos-filler, async persist hooks (web channel;
  voice-core owner). *(The phone deltas that were here — `app/phone/real_agent.py`/
  `bridge.py` — are void: those files were deleted by the Pipecat port; the phone media
  path lives in `app/voice/` now, owned per `2026-07-09-pipecat-voice-port`.)*
- `app/agent/prompts.py`/`pipeline.py`: slimming + first-clause (voice-core owner;
  `build_system_prompt` is also reused verbatim by the Pipecat phone pipeline).
- `Makefile`: `latency` row. `.gitignore`: `data/latency/`, `data/tts_cache/`.
