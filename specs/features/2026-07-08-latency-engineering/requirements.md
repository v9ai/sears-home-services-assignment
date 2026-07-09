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

## Root-cause analysis (MEASURED 2026-07-08 — probes N=3–5, instrumented real turn)

Evidence collected via micro-benchmarks + an instrumented production `run_turn`
(gpt-4.1-mini, web-path shape, serialized TTS exactly as `_speak` does):

| Level | Measured | Root cause (evidence) |
|---|---|---|
| **L5 TTS — DOMINANT** | first-byte p50 573 ms; full-sentence synth p50 1324 ms; **serialized TTS wall = 11.34 s of a 15.04 s turn (75%)** | Per-sentence synthesis is awaited inline: sentence N+1 cannot start until N finishes, AND the inline await back-pressures `run_turn` consumption, delaying later sentences/tools. 7 sentences × ~1.3 s serial. |
| **L4 agent structure** | LLM TTFT alone p50 801 ms; first tool batch at 2.44 s; **first sentence ready 3.43 s**; mid-turn tool batch at 6.80 s | Head latency = tool-call round trip(s) before any prose (2 parallel tools, then the reply); NOT raw model speed. First audio = 3.43 s + 1.25 s TTS = **4.68 s**. |
| **L1 network** | OpenAI API TTFB from dev machine: 0.72–1.03 s (p50 ≈ 0.93 s); CF worker: 0.36–0.44 s | High client↔OpenAI RTT taxes EVERY call — a single turn makes ~10+ OpenAI calls (2–3 LLM + 7 TTS). The HOSTED container (us-east) has materially lower RTT to OpenAI: run demos hosted (hosted greeting measured 1.21 s vs local 3.7 s headless first-sentence). |
| L5b constants | greeting/filler/fallback re-synthesized every call (~0.5–1.3 s each) | No cache — being fixed (O1 partially in flight: `app/agent/tts_cache.py` + `app/agent/fillers.py` observed in the WS path). |
| L7 app IO | `persist_session` (a Neon round trip: est. 100–300 ms from dev; less in-region) + recording `open().write` awaited inline per turn | On the critical path between turns; best-effort semantics already allow fire-and-forget. |
| L3 STT | p50 588 ms (184 KB wav) | Within its 900 ms budget; not a root cause. |
| L2 VAD | fixed 300 ms hangover | By design; only tunable, not a bug. |
| L6 bridge | 20 ms framing/pacing | Negligible; playback is real-time by definition. |

### Deep RCA — level internals (measured 2026-07-08, round 2)

| Internal | Measured | Implication |
|---|---|---|
| **L5i web audio format** | TTS TTFB **mp3 904 ms vs pcm 637 ms** (p50/3, same sentence) | The web channel pays **~270 ms extra per sentence** purely for server-side mp3 encoding — 7 sentences ≈ 1.9 s of pure format tax. Phone already uses pcm. |
| **L4i prompt token load** | system prompt ≈ **1,045 tokens on EVERY LLM call** (4,180 chars empty case file; 4,159 after appliance identified — effectively constant) | 2+ LLM calls per tool turn each re-upload ~1 k tokens; the spec'd knowledge-vocab conditional (P1-2) is NOT yet implemented (identified case ≈ same size). TTFT is input-sensitive. |
| **L4ii two-LLM-call floor** | TTFT ≈ 800 ms × 2 sequential calls per tool turn (tools at 2.44 s, first sentence 3.43 s) | A tool-using turn has a ~1.6–2 s hard floor before any prose regardless of TTS — P0-4 (prose-before-tools) is the only lever that beats the floor perceptually. |
| **L4iii turn verbosity** | 7–9 sentences per agent reply (measured across live turns) | Voice UX wants 2–3; verbosity multiplies ΣTTS AND caller listening time. A prompt-level cap halves the tail for free. |
| **L1i container→OpenAI RTT** | **UNMEASURED** — probes so far ran dev-side only (dev→OpenAI 0.93 s) | The one missing number. Needs a flag-gated in-container probe endpoint (O10) to measure from us-east; expected ~100–250 ms, which would shrink every per-call figure above on the hosted stack. |
| **L1ii cold start** | first hosted request after idle: 500 + ~33 s window (container boot + alembic + seed + imports); `sleepAfter=30m` | Any reviewer calling after 30 idle minutes hits it. Keep-warm needed (O11). |
| **L6i web client playback** | per-sentence mp3 Blobs each decode in a fresh `<audio>` element | Inter-sentence decode gaps (~50–150 ms each) = audible stutter between sentences even when server timing is perfect (O12). |

### Deeper RCA — round 3: request anatomy & negative findings (measured 2026-07-08)

| Internal | Measured | Verdict |
|---|---|---|
| **L4iv tool-schema payload** | 8 tools = **~1,757 tok per LLM call** — bigger than the system prompt (1,045); total per-call upload ≈ 2,900 tok, ×2 calls/turn ≈ 5,800 tok re-uploaded per tool turn | **Cost issue, NOT latency** (see L4vi). Verbose tool docstrings (JSON response shapes etc.) are the bulk → O13, cost-tagged |
| **L4vi TTFT payload sensitivity** | TRUE agent-shaped TTFT (full prompt + tools): **727 ms — statistically identical to bare 801 ms** | **NEGATIVE FINDING that re-ranks the menu**: at our payload scale, input size does NOT drive TTFT. **P1-2 prompt slimming and O13 are hereby downgraded from latency fixes to cost fixes.** The real latency levers remain: parallel TTS (P0-3), prose-before-tools (P0-4), caching (P0-1/2), web audio format (O9), verbosity (O8), region (P2-3) |
| **L4v memory growth** | ~294 tok of chat history by turn 6 | Negligible — the case-file architecture (facts live outside chat history) keeps this naturally small. No action |
| **L5iii TTS instructions param** | TTFB 624 ms with instructions vs 651 ms without | **Free** — keep the warm-voice instructions; no fix needed |
| **L7iii Neon round-trip** | **120 ms warm** (dev→us-east; persist = 2–3 statements ≈ 250–400 ms inline per turn) | Grounds O4 (async IO) with a real number; in-region container pays less but still nonzero |

**Ranked verdict**: (1) serialized per-sentence TTS — 75% of turn wall; (2) tool-round-trip
head before first prose; (3) client↔OpenAI RTT multiplied by per-turn call count —
mitigated by running against the hosted us-east stack; (4) uncached constant strings;
(5) inline Neon persist + file writes.

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
See `runbook.md` in this spec directory for the filled-in decision tree.
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
- **P0-3 · L5 — parallel TTS pipeline (added from the measured RCA — the dominant
  fix)**: bounded producer/consumer (lookahead 2): synthesis of sentence N+1 starts
  while N streams; ordered emission preserved; the `run_turn` event loop is never
  blocked on synthesis. Expected: turn wall bounded by max(LLM, longest TTS tail)
  instead of ΣTTS — from the measured 15.04 s toward ~5–6 s for the same 7-sentence
  turn. Applies to `app/ws/routes.py` (`_speak` loop) and `app/phone/real_agent.py`
  (`_say` loop).
- **P0-4 · L4 — first-prose-before-tools prompt shape**: instruct the agent to open
  with one short acknowledgment sentence BEFORE tool calls (LlamaIndex streams it →
  first audio at ~TTFT+TTS-first-byte ≈ 1.5–2 s) — complements the eos-filler; the
  cached filler remains the guarantee when the model calls tools immediately.
- **P1-1 · L7 — off-critical-path IO**: `persist_session` + recording writes via
  `asyncio.create_task` (fire-and-forget, failures logged). Already best-effort;
  semantics unchanged.
- **P1-2 · L4 — prompt slimming (RETAGGED 2026-07-08: cost fix, not latency)** —
  round-3 measurement showed TTFT is payload-insensitive at our scale (727 ms full vs
  801 ms bare); still worth doing for per-turn token cost (~5,800 tok/turn re-upload)
  but it buys no first-audio time. Compact case-file JSON; conditional knowledge
  vocabulary.
- **O13 · L4iv — tool-schema slimming (cost)**: terse LLM-visible tool descriptions
  (move verbose JSON-shape documentation into code comments, out of docstrings);
  ~1,757 tok/call today, target ≤ ~600. Cost-tagged for the same round-3 reason.
- **P1-3 · L4/L5 — first-clause chunking**: `split_ready_sentences` emits the first
  clause (comma/semicolon boundary) for a turn's FIRST audio, full sentences after.
- **P2-1 · L4 — tool round-trip reduction**: prompt guidance for parallel tool calls +
  answer-immediately-after-results; LlamaIndex parallel tool execution where emitted.
- **P2-2 · L4 — provider A/B decision gate**: `make latency` DeepSeek vs
  `LLM_PROVIDER=openai` TTFT/first-sentence side-by-side; a recorded decision pins the
  demo-day default (an explicit, recorded escape-hatch use if OpenAI wins — the
  Model-provider boundary stays intact). **First sample (2026-07-08, N=1 each, same
  scenario)**: DeepSeek 4.07 s first sentence / 11.79 s full turn; gpt-4o 6.16 s /
  7.54 s. User pinned `LLM_PROVIDER=openai` as the demo-day default same day (boundary
  amendment); the N=5 `make latency` A/B still runs to confirm or revisit.
  **Model sweep (2026-07-08, N=3 each, live-turn probe, ranked by median
  first-sentence; DQ = tool/case-file miss on any run):**

  | Model | med first-sentence | med full turn | qualified |
  |---|---|---|---|
  | **gpt-4.1-mini (pinned)** | **4.29 s** | 11.02 s | ✓ 3/3 (4 tools) |
  | gpt-4o (prev default) | 6.16 s | 7.54 s | ✓ (N=1) |
  | gpt-4o-mini | 7.77 s | 9.67 s | ✓ 3/3 |
  | gpt-4.1-nano | 1.96 s | 4.04 s | **DQ — zero tool calls 2/3** |
  | gpt-5-mini | 31.56 s | 33.63 s | DQ (reasoning tokens + tool miss) |
  | gpt-5-nano | 28.75 s | 31.11 s | ✓ but 28 s+ — unusable for voice |
  | DeepSeek deepseek-chat | 4.07 s (N=1) | 11.79 s | ✓ |

  Confirmation run on the pinned config: 3.74 s first sentence / 9.03 s full turn.
  Key findings recorded: raw speed without tool reliability disqualifies (4.1-nano);
  reasoning-family models are unusable for voice TTFT (gpt-5-mini/nano).
- **P2-3 · L1 — run against the hosted stack** (measured: dev↔OpenAI TTFB ~0.93 s
  vs CF-worker RTT 0.4 s; the us-east container sits far closer to OpenAI): demos and
  the live number already terminate on the hosted Worker — keep it that way; local
  laptops are for development only. (The original tunnel-hop concern is moot: ngrok
  is out of the serving path entirely.)
- **P3-1 · L2 — VAD hangover 300→200 ms** behind an env knob, with a false-cut guard
  metric (mid-utterance splits must not increase).
- **O8 · L4iii — voice-reply length cap (prompt)**: persona instruction — replies ≤ 3
  short sentences per turn on voice channels; ask one question at a time. Halves ΣTTS
  and listening time; validated by the existing Conversation Completeness metric not
  regressing.
- **O9 · L5i — web audio format → pcm/wav** (measured 270 ms/sentence mp3 tax):
  `_speak` streams pcm (or wav-wrapped) like the phone path; `web/lib/audioQueue.ts`
  plays via WebAudio buffers instead of per-blob `<audio>`. Bandwidth tradeoff
  recorded (24 kHz pcm ≈ 64 KB/s base64 — fine for broadband; revisit opus if not).
- **O10 · L1i — flag-gated `/debug/latency-probe` endpoint**: runs the micro-probes
  (OpenAI TTFB, LLM TTFT, TTS TTFB, Neon round-trip) FROM the container, returns
  JSON; `LATENCY_PROBE_ENABLED` default off. Closes the one unmeasured number
  (container→OpenAI RTT) and gives `make latency --hosted` a target.
- **O11 · L1ii — keep-warm**: Cloudflare cron trigger (or external ping) hits
  `/healthz` every 10 min < `sleepAfter=30m`, so no reviewer ever pays the ~33 s cold
  start; entrypoint also logs cold-start duration as a tracked metric.
- **O12 · L6i — gapless web playback**: continuous WebAudio buffer queue (pairs with
  O9's pcm) replacing per-sentence `<audio>` elements; eliminates inter-sentence
  decode gaps.

### Regression-proof test contract (added 2026-07-08 — "prove it's fixed, keep it fixed")

`tests/latency/` — deterministic, fake-based, **zero live APIs**, runs in `make test`
forever. Each test names the root cause it guards; a reintroduced regression turns the
suite red, not the demo slow.

| Test | Guards | Mechanism (deterministic) |
|---|---|---|
| `test_pipeline_parallelism_beats_serial_and_preserves_order` | **P0-3 / RCA #1** (serialized TTS, the 75%) | FakeSynth with fixed 200 ms/sentence; 3-sentence scripted turn: wall < Σsynth (e.g. < 450 ms vs 600 ms serial), synth-start of sentence N+1 precedes synth-end of N (timestamps), audio emission order preserved |
| `test_feed_never_blocks_on_synthesis` | RCA #1's second half (inline await stalls the agent stream) | slow FakeSynth (500 ms): feeding all sentences is near-instant — the agent event loop never waits on TTS |
| `test_constant_lines_never_hit_tts_api` | O1 / RCA #4 (uncached constants) | spy on the raw API synth: greeting + filler + fallback through both channel entry points → **zero API calls** on warm cache; cache filename embeds the text hash (stale-cache guard when GREETING changes) |
| `test_filler_beats_slow_llm` | O2 (perceived dead air) | FakeLLM with 800 ms delayed first token: filler audio emitted well inside half the filler budget after `user_text` receipt (web) / turn close (phone) |
| `test_persist_off_critical_path` | O4 / RCA #5 (inline Neon+file IO) | FakeDB with 500 ms latency: last audio frame of the turn emitted WITHOUT awaiting persist; persist still lands (await the background task); an injected write failure never raises into the turn |
| `test_first_clause_chunker` | O6 | unit: first emission may break at clause boundary ≥ ~40 chars; later emissions at sentence boundaries; concatenation loses no text |
| `test_pipeline_overhead_floor` | **the structural "never again" guard** | all fakes at pinned delays (LLM TTFT 800 ms, TTS first-byte 550 ms): measured first-audio ≤ theoretical floor + **150 ms pipeline overhead budget** — ANY reintroduced serialization, inline await, or synchronous IO on the turn path blows this single assertion |
| prompt static assert | P0-4 | `build_system_prompt` contains the acknowledge-before-tools instruction (behavioral proof lives in the eval scenario below) |

Live-layer tripwires (key-gated, in `make latency`, not `make test`):
- **Serialization ratio**: for multi-sentence live turns, `turn_wall ≤ 0.7 × Σ(TTS busy time)` must hold once P0-3 lands — a live regression detector for the exact measured failure shape (11.34 s/15.04 s = 0.75 was the broken baseline).
- **P0-4 eval scenario**: first agent transcript event precedes the first tool
  invocation on ≥ 4/5 sampled live turns (rubric-level, tolerant of model variance).

### Stage budgets (the contract; hard once P0+P1 land)
MOVED (2026-07-09, latency-centralization): the numbers now live canonically in
`specs/latency/budgets.md` (machine source of truth `app/latency/budgets.py`;
lockstep enforced by `tests/latency/test_budget_spec_sync.py`). This spec still owns
the *policy* — which stages have budgets, the advisory→hard flip — but restates no
numbers. Web: submit→first audio, same envelope minus L1–L3, stricter (see the
canonical doc).

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
  no behavior change without the suite green; budgets versioned in
  `specs/latency/budgets.md` + `app/latency/budgets.py` only (amended 2026-07-09,
  latency-centralization — previously "in this spec only").
- Open question (deferred): whether greeting cache invalidates on `GREETING` string
  change — hash the text into the cache filename (record as the implementation rule).
