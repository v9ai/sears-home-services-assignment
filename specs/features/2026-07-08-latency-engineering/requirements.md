# Latency Engineering (test · debug · fix, every level) — Requirements

## Source
User directive (2026-07-08):
> there is a lag when calling — needs a spec which can test debug and fix all lags on
> every level

Resolves the two open latency decisions: testing-evals Decision 6 (advisory→hard
latency gate) and deepseek-agent-llm validation #2 (single 4.07 s sample, mitigation
undecided).

## The seven levels (measured/expected costs, code anchors)

| # | Level | Code anchor | Known/expected cost |
|---|---|---|---|
| L1 | Twilio ⇄ tunnel network | ngrok Compose profile; Cloudflare hosted alternative | free-tier tunnel hop, regionless RTT |
| L2 | VAD endpointing | `app/phone/vad.py` `TurnSegmenter` | fixed ~300 ms hangover after end of speech |
| L3 | STT | `app/phone/stt.py` (buffered utterance → `gpt-4o-transcribe`) | 400–900 ms per utterance |
| L4 | Agent LLM | `app/agent/core.py` (DeepSeek), `app/agent/pipeline.py` sentence chunker | **measured 4.07 s to first sentence**; ×4 tool round trips per turn (11.79 s full turn) — the dominant lag |
| L5 | TTS | `app/agent/tts.py` — per-sentence synth, incl. the CONSTANT greeting/filler strings re-synthesized every call | 300–500 ms first byte, each |
| L6 | Bridge/playback | `app/phone/bridge.py` (queue, 20 ms framing, 24 k→8 k resample) | small; greeting blocked on synth |
| L7 | App overhead | `persist_session` + recording writes awaited inline per turn (`app/ws/routes.py`, `app/phone/real_agent.py`) | DB + file IO on the critical path |

## Scope

### A. Test — `make latency` (scripts/latency_bench.py)
- **Per-stage micro-benchmarks** (key-gated, skip-loud): LLM TTFT probe (one
  `get_llm()` streaming call, no tools) · STT-only timing on a fixture wav · TTS TTFB
  probe. p50/p95 over N=5 each.
- **End-to-end**: the live driver runs M scenarios recording the full per-turn trace —
  the exact fields telephony plan group 5 specifies (`eos_to_stt_ms`,
  `stt_to_agent_first_token_ms`, `agent_first_token_to_first_audio_ms`,
  `eos_to_first_audio_ms`, `turn_total_ms`) plus web-channel equivalents
  (submit→first-token/first-audio).
- **Report artifact**: `data/latency/{ts}.json` + rendered table with a budget column
  and PASS/FAIL per stage — comparable across runs (before/after each fix).

### B. Debug — the runbook (stage over budget → level → fix)
- Decision tree keyed on the stage columns of the report.
- Live-call stage timing via `twilio_debug tail --call-sid` (observability events).
- Network-vs-provider separation without packet capture: `curl -w '%{time_starttransfer}'`
  TTFB against `api.deepseek.com`, `api.openai.com`, and the tunnel URL — if network
  RTT is small and LLM TTFT is big, the lag is provider-side (L4), not L1.

### C. Fix menu (prioritized; each names its level, mechanism, expected gain, validation)
- **P0-1 · L5 — static audio cache for constant strings** (`data/tts_cache/`):
  greeting, tool filler, failure fallback synthesized once, played from disk. Removes
  TTS from call-answer + filler paths entirely (~400 ms each; greeting near-instant).
- **P0-2 · L4-perceived — filler at end-of-speech, not on `ToolInvoked`**: play the
  cached filler the moment the turn closes (phone) / on submit (web). Masks the whole
  STT+LLM TTFT window — the single biggest *perceived* fix.
- **P1-1 · L7 — off-critical-path IO**: `persist_session` + recording writes via
  `asyncio.create_task` (fire-and-forget, failures logged). Already best-effort;
  semantics unchanged.
- **P1-2 · L4 — prompt slimming**: compact case-file JSON encoding; knowledge
  vocabulary section only while the appliance is unidentified. Token count measured
  before/after (DeepSeek TTFT is input-token-sensitive).
- **P1-3 · L4/L5 — first-clause chunking**: `split_ready_sentences` emits the first
  clause (comma/semicolon boundary) for a turn's FIRST audio, full sentences after.
- **P2-1 · L4 — tool round-trip reduction**: prompt guidance for parallel tool calls +
  answer-immediately-after-results; LlamaIndex parallel tool execution where emitted.
- **P2-2 · L4 — provider A/B decision gate**: `make latency` DeepSeek vs
  `LLM_PROVIDER=openai` TTFT/first-sentence side-by-side; a recorded decision pins the
  demo-day default (an explicit, recorded escape-hatch use if OpenAI wins — the
  Model-provider boundary stays intact).
- **P2-3 · L1 — kill the tunnel hop**: hosted Cloudflare deploy for webhook/WSS;
  interim `ngrok --region` nearest + keepalive.
- **P3-1 · L2 — VAD hangover 300→200 ms** behind an env knob, with a false-cut guard
  metric (mid-utterance splits must not increase).

### Stage budgets (the contract; hard once P0+P1 land)
`eos_to_stt_ms` ≤ 900 · `stt_to_first_token_ms` ≤ 1200 ·
`first_token_to_first_sentence_ms` ≤ 800 · `tts_first_byte_ms` ≤ 500 ·
`first_outbound_frame_ms` ≤ 100 · **e2e eos→first-audio p50 ≤ 2.5 s / p95 ≤ 4 s** ·
answer→greeting ≤ 1.5 s (≤ 0.5 s with the cache) · filler audible ≤ 800 ms after eos.
Web: submit→first audio, same envelope minus L1–L3.

### Not included (deferred)
- OpenAI Realtime API (forbidden pattern; its revisit clause is exactly "if this
  budget fails" — P0–P2 must be exhausted first and the decision recorded).
- Streaming STT rework, speculative decoding, self-hosted/GPU models.

## Decisions
1. **Per-stage budgets, not just end-to-end** — regressions localize to a level; the
   report's PASS/FAIL column is the debugging entry point.
2. **Fixes land behind existing gates** — the 200+ test suite staying green is the
   behavioral-equivalence proof for every fix (esp. P1-1's async IO).
3. **Advisory→hard flip criteria** — after P0+P1 land AND two consecutive
   `make latency` runs pass all stage budgets at p50; the flip updates testing-evals
   Decision 6 and closes deepseek-agent-llm validation #2.
4. **Perceived latency counts** — filler/greeting fixes don't reduce e2e ms but are
   first-class (assignment §6 "the caller's experience matters"); budgets include
   answer→greeting and eos→filler for that reason.

## Architecture impact
- Invariant-preserving. New: `scripts/latency_bench.py`, `data/latency/`,
  `data/tts_cache/`, `make latency`. P0/P1 code changes touch ws/agent/phone paths —
  declared as lead-applied deltas (those files have owners per COORDINATION §3).

## Context
- Builds on: telephony plan group 5 trace fields + 5b observability events;
  `evals/live_driver.py`; the twilio-cli-debug spec's `tail`.
- Constraints: Model-provider boundary (P2-2 is an explicit recorded exception path);
  no behavior change without the suite green; budgets versioned in this spec only.
- Open question (deferred): whether greeting cache invalidates on `GREETING` string
  change — hash the text into the cache filename (record as the implementation rule).
