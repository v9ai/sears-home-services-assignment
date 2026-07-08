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

## 3. P0 fixes                                          ⏸ review after this group
      *(O1 cache + O2 filler partially IN FLIGHT by a parallel agent —
      `app/agent/tts_cache.py` + `app/agent/fillers.py` observed wired into
      `app/ws/routes.py`; verify both channels + cache-hit tests before ticking.)*
- [ ] **P0-3 parallel TTS pipeline** (the measured 75% — see requirements): bounded
      lookahead-2 producer/consumer in both channel loops; ordering test.
- [ ] **P0-4 first-prose-before-tools** prompt line + verify a short acknowledgment
      streams before the first tool batch.
- [ ] P0-1 TTS cache: `data/tts_cache/{sha1(text)}.{mp3|pcm}` for GREETING,
      TOOL_FILLER, TURN_FAILED_FALLBACK; cache-first playback in both channels.
- [ ] P0-2 filler at end-of-speech (phone: on turn close; web: on submit), cached.
- [ ] `make latency` rerun; expect answer→greeting ≤ 0.5 s, filler ≤ 800 ms.

## 4. P1 fixes
- [ ] P1-1 async IO: persist/recording via `asyncio.create_task`; ordering test.
- [ ] P1-2 prompt slimming (compact case-file JSON; conditional knowledge vocab);
      token counts logged before/after.
- [ ] P1-3 first-clause chunking for a turn's first audio.
- [ ] `make latency` rerun; expect first_token_to_first_sentence_ms ≤ 800.

## 4b. Regression-proof tests (requirements § Regression-proof test contract)
- [ ] `tests/latency/` suite: parallelism, backpressure, cache-hit, filler-timing,
      async-IO, first-clause, and the **pipeline-overhead floor** guard — all
      fake-based, zero live APIs, permanent in `make test`.
- [ ] Live tripwires wired into `make latency`: serialization ratio ≤ 0.7 ·
      P0-4 prose-before-tools sampling.
- [ ] Every test lands in the SAME commit as (or before) its fix — a fix without its
      guard doesn't tick.

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
