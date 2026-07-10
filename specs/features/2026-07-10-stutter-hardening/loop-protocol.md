---
name: stutter-iterate
description: Run ONE bounded phone-audio-quality iteration for the voice agent — measure the hermetic stutter bench (echo/clear/tail/pacing probes), pick the single biggest remaining lever, apply one fix with its regression test, validate quality gates (genuine barge-in must survive), accept or revert, record in the loop ledger. Built on the loop-v2 conventions (lanes, collaborator-dirt rule, decision packets). Designed to be driven by /loop (self-paced); prints STUTTER_LOOP CONTINUE or STOP as its final line.
---

# Stutter Iterate — one loop iteration

You are executing ONE iteration of the phone-audio-quality loop. The target defect
class is the **barge-in echo loop** and its relatives (RCA 2026-07-09,
`docs/local-twilio-run.md` "Stuttering during the reply"): an AEC-less PSTN leg
returns the bot's own TTS on the inbound stream; anything that lets that echo open a
user turn fires interruption → Twilio `clear` → the reply is flushed and restarts →
gaps, garble, repeated speech. The first guard
(`app/voice/bot.py::_build_user_turn_strategies`, `MinWordsUserTurnStartStrategy`,
`VOICE_BARGEIN_MIN_WORDS`) landed 2026-07-09 with
`tests/voice/test_bargein_guard.py`; this loop hardens the remaining levers WITHOUT
over-correcting.

This loop adopts the v2 conventions from `.claude/skills/latency-maximize/` (its four
autopsy findings apply here too): work on `main` with the collaborator-dirt rule, not
a fictional branch; never judge a timing probe on one run; eval failures must
reproduce to count; human-decision items produce packets and `awaiting-human`, never
dead stops.

Durable state: ledger `specs/features/2026-07-10-stutter-hardening/loop-ledger.md`
(read it first, trust it over memory, update it last). Iteration 1 (`q1`) commits a
protocol copy to `specs/features/2026-07-10-stutter-hardening/loop-protocol.md` — on
any drift between this file and that one, the committed copy wins.

FINAL output line, exactly one of:

    STUTTER_LOOP: CONTINUE (iteration <N> done: <fix-id> <accepted|reverted|blocked|awaiting-human>; next: <fix-id>)
    STUTTER_LOOP: STOP (<reason>)

When driven by `/loop`: on CONTINUE schedule the next wakeup immediately (iterations
are hermetic; the pacing bound is `make test`, ~8 min). On STOP end the loop
(ScheduleWakeup stop). If invoked while the ledger says `stopped`, exit at §1 with
zero side effects.

Canonical references (read as needed, don't restate):
- RCA + incident history: `docs/local-twilio-run.md` §"Stuttering during the reply",
  §"Agent replying to phantom turns"
- Current guard + counters: `app/voice/bot.py` (`_build_user_turn_strategies`,
  `VOICE_BARGEIN_MIN_WORDS_DEFAULT`), `app/voice/serializer.py` (`bargein_clears`)
- Tests to keep green: `tests/voice/test_bargein_guard.py`,
  `tests/voice/test_serializer.py`, `tests/voice/test_voice_latency_e2e.py`,
  `tests/voice/test_vad_config.py`
- Pipecat levers (verified in 1.5.0): `MinWordsUserTurnStartStrategy`
  (`pipecat.turns.user_start`), `user_mute` strategies (`FirstSpeech`,
  `MuteUntilFirstBotComplete`, `Always`), `audio_out_10ms_chunks`
  (TransportParams, default 4 = 40 ms frames)

## §0 Invariants (checked on every accept; violating ANY is a hard reject)

The loop's job is to make echo unable to stutter the reply — NEVER to make the bot
uninterruptible or slower:

1. **Genuine barge-in survives**: a real ≥`min_words` talk-over while the bot speaks
   must still open the turn (probe `echo_storm.genuine_bargein_honored`, and
   `test_bargein_guard.py::test_real_barge_in_still_interrupts`).
2. **No wholesale interruption kill**: `enable_interruptions=False`,
   `AlwaysUserMuteStrategy`, or a whole-call half-duplex flip is lane-H material
   (packet + `awaiting-human`), never a lane-F fix.
3. **Turn-stop / endpointing untouched** unless the fix-id targets it; never below
   `VAD_STOP_SECS_MIN_SAFE`. The latency loop owns latency — if a stutter fix moves a
   latency number beyond noise, record it in the ledger and flag the latency ledger.
4. **Never loosen a probe budget to make a run pass**; budget changes are human-only.
   Never touch `.env`. Never weaken/delete failing tests to pass gates.
5. One fix per iteration, minimal diff, regression test in the SAME commit,
   `git revert` (never reset) on reject — history stays bisectable.

## §1 Preconditions (abort loudly; never repair silently)

1. Ledger `state: stopped (…)` → `STUTTER_LOOP: STOP (already stopped: <reason>)`.
   No ledger → iteration 1.
2. **Branch = `main`.** Iterations are identified by commit-message prefix
   `stutter-loop i<N>:`, greppable and bisectable.
3. **Collaborator-dirt rule**: read `git status --porcelain`. Proceed iff the dirty
   files do NOT intersect this iteration's planned fix surface; list them in the
   ledger entry. If they DO intersect → pick the next queue item whose surface is
   clean; if none → STOP (surface contention — human intervention).
4. Keys: none needed for the bench (hermetic by design — a live PSTN call cannot be
   automated). Eval, when mandatory (§5), needs judge keys from `.env`
   (`set -a; source .env; set +a`); a judge-key SKIP counts as NOT RUN and rejects a
   mandatory case.
5. Cost caps (ledger header): `iteration > 10` → STOP (cost-cap);
   `judged_eval_runs_total >= 8` → STOP (cost-cap).

## §2 MEASURE

1. **Hermetic guard first**: `.venv/bin/pytest tests/voice tests/latency -q`
   (with `FILLER_ENABLED=0` while the filler workstream's env-sensitivity is
   unresolved — note it in the ledger when applied). Red → STOP (tree already broken).
2. **Bench**: `make stutter` → `data/stutter/<utc-ts>.json` (exists from `q1`
   onward; on iteration 1 building it IS the fix). Deterministic probes
   (`echo_storm`, `clear_accounting`, `phantom_tail`) are single-run. The **pacing
   probe is timing-noisy**: the bench runs it 3× in-process and reports the median +
   `noise_pct = (max−min)/median × 100` — never judge pacing on one sample.
3. Baseline reuse: the previous iteration's `after_report` is reusable iff it still
   exists and no `app/voice/` file changed since; otherwise rerun (the bench is free).

## §3 DIAGNOSE

1. Rank failing/regressing probes by defect severity: `echo_storm` >
   `clear_accounting` > `phantom_tail` > `pacing` (reply-chopping beats cosmetic
   jitter).
2. **Live evidence** (optional, never required to proceed): `data/recordings/*/call.wav`
   newer than the last iteration, or `twilio.call.summary` lines in reachable logs →
   extract `barge_ins` vs turns per call (after `q2`, run the analyzer for gap/restart
   verdicts). A real call showing `barge_ins > 0` without genuine talk-over, or a user
   stutter report, OVERRIDES lane order — record the override rationale.
3. Choose the fix: worst probe → lane row below → minus ledger entries
   `decision: reverted|blocked|awaiting-human` (a retry requires a NEW hypothesis
   recorded in the ledger).

## §4 LANES + fix queue

Work lanes in order Q → F → H, skipping items the ledger shows done. Within a lane,
reordering requires a recorded rationale.

**Lane Q — measurement & observability (build before spending on product fixes):**

| id | What | Class |
|----|------|-------|
| q1 | Build the bench: `scripts/stutter_bench.py` + `make stutter` + `tests/test_stutter_bench.py` (schema §9); create the ledger; commit the protocol copy; archive the first report | neutral |
| q2 | `scripts/call_audio_report.py`: offline stereo-WAV analyzer for `data/recordings/*/call.wav` (bot = right channel) — mid-reply silence gaps > 250 ms, repeated-segment (restart) detection via short-window autocorrelation, per-call JSON verdict; unit-tested on synthetic WAVs with injected gaps/restarts | neutral |
| q3 | Storm tripwire: `log_event` `voice.bargein.storm` when `bargein_clears` grows >2 within one bot reply (serializer counts; add a per-reply window reset on `BotStartedSpeakingFrame`) — makes a live recurrence diagnosable mid-call, not just at call end | neutral |

**Lane F — guard fixes (one per iteration; regression test same commit; eval
mandatory since all touch `app/voice/`):**

| id | Target probe | What |
|----|--------------|------|
| f1 | `phantom_tail` | Echo-tail guard: subclass `MinWordsUserTurnStartStrategy` that keeps requiring `min_words` for `VOICE_BARGEIN_TAIL_MS` (default 400) after `BotStoppedSpeakingFrame`, instead of dropping to 1 word the instant the bot stops — the trailing-echo window from the second documented incident. Knob env-tunable, `0` = plain MinWords. Flips the probe's `enforced` to true in the same commit. Tests mirror `test_bargein_guard.py` style. |
| f2 | `pacing` (cadence) | `audio_out_10ms_chunks=2` in `FastAPIWebsocketParams` (`app/voice/bot.py::run_bot`) — Twilio-idiomatic 20 ms/160-byte µ-law frames instead of default 40 ms. Env `VOICE_OUT_10MS_CHUNKS` default 2, documented in `.env.example`; the probe's `cadence_ms` assertion updates 40→20 in the SAME commit. |
| f3 | `pacing` (gaps) | Pacing isolation: move inline CPU work off the outbound send loop (e.g. `AudioBufferProcessor` buffer growth, resample cost). EVIDENCE-GATED: only if the pacing probe median or q2's live analyzer shows gaps; measure before touching. |

**Lane H — human-decision packets (measure inputs, write the packet as a PROPOSAL
block in `specs/features/2026-07-10-stutter-hardening/`, mark `awaiting-human`, move
on — never decide):**

| id | Packet |
|----|--------|
| h1 | Greeting shield: should `FirstSpeechUserMuteStrategy` (or `MuteUntilFirstBotComplete`) mute the caller during the greeting? Inputs: live evidence of greeting-time phantom turns (q2 verdicts), plus the cost — a real caller interrupting the greeting is ignored. Two options with the data for each. |
| h2 | Knob tuning: `VOICE_BARGEIN_MIN_WORDS` 2 vs 3, `use_interim` on/off. Inputs: live false-positive (echo interrupted anyway) vs false-negative (real barge-in missed/slow) counts from q2 + summary logs. Word-count trades barge-in responsiveness vs echo immunity — human call. |
| h3 | Full half-duplex (`AlwaysUserMuteStrategy` — no barge-in at all): ONLY if live evidence shows min-words + tail guard still insufficient on real PSTN echo. Inputs: q2 verdicts across ≥3 calls, `barge_ins` storms in summaries. This is the nuclear option; the packet must say what is lost. |

Terminal (§8.1 only): `gate-flip` — wire `make stutter` into `make test` as a hard
gate; tick the phone-audio line in the telephony spec validation doc.

## §5 IMPROVE — exactly ONE fix-id, minimal diff, same-commit regression test

Commit message `stutter-loop i<N>: <fix-id> — <one line>`.
**Forbidden, no exceptions:** interruption-kill outside lane H; probe-budget or VAD
floor edits; touching `.env`; provider swaps (not this loop's surface); weakening
eval thresholds or deleting failing tests.

## §6 VALIDATE (cheap → expensive)

1. `make lint`
2. Full `make test`. A failure in collaborator-owned files you did not touch:
   record + re-run that file once; if it passes in isolation it does not block —
   say so in the ledger (`known_failing_tests` header field tracks the standing set,
   currently the `FILLER_ENABLED`-sensitive e2e pair if still unfixed).
3. Eval: MANDATORY for lane F (all touch `app/voice/`); `judged_eval_runs_total += 1`.
   Use `make eval-hermetic` if the latency loop's q0-3 split has landed, else full
   `make eval`. Either way a failure must reproduce on ONE retry of the failing test
   to count as a regression. Skippable ONLY for pure-harness lane-Q diffs with the
   justification recorded.
4. `make stutter` rerun → after-report; diff probes against baseline.

## §7 ACCEPT / REVERT

- **Lane F fixes**: accept iff the target probe improved or crossed FAIL→PASS
  (pacing: on the 3-sample median, beyond its own `noise_pct` band); AND no other
  probe crossed PASS→FAIL; AND `genuine_bargein_honored` stayed true; AND §0
  invariants hold; AND gates green (reproducible-eval rule). **Eval regression =
  hard reject even if the probe improved.**
- **Lane Q (neutral)**: gates green + no probe PASS→FAIL. No improvement bar.
- **Lane H (packets)**: the packet file exists, is committed, and states its decision
  options with measured inputs — outcome `awaiting-human`.
- On reject: `git revert <sha>`, record the negative finding — what was tried, probe
  deltas, and a hypothesis for why it failed — so §3 never retries it blind.

## §8 RECORD

Append one ledger entry, update header counters, commit (accepts: amend the ledger
into the fix commit; rejects: separate `stutter-loop i<N>: record <fix-id>
(reverted)` commit; never rewrite shared history).

Ledger header:

```markdown
# Stutter Loop Ledger
state: running
iteration: <N>
judged_eval_runs_total: <N>
consecutive_all_pass: <N>
lane_no_accepts: {Q: 0, F: 0}
known_failing_tests: <exact ids, or none>
```

Per-iteration entry: `## Iteration <N> — <fix-id> — <ACCEPTED|REVERTED|BLOCKED|AWAITING-HUMAN>`
+ one fenced JSON object:

```json
{
  "iteration": 0,
  "timestamp_utc": "",
  "lane": "Q|F|H",
  "fix_id": "",
  "description": "",
  "baseline_report": "<filename in data/stutter/>",
  "after_report": "<filename>",
  "target_probe": "",
  "probes_delta": {},
  "pacing_noise_pct": 0,
  "live_evidence": null,
  "collaborator_dirty_files": [],
  "gates": {"lint": "", "test": "", "eval": "", "stutter_overall": false},
  "decision": "accepted | reverted | blocked | awaiting-human",
  "commit": "",
  "revert_commit": null,
  "notes": ""
}
```

`timestamp_utc` from `date -u +%Y-%m-%dT%H:%M:%SZ`.

## §9 STOP / CONTINUE (checked after RECORD, in order)

1. **Success**: last two bench reports both `overall_pass: true` AND q1–q3 + f1–f2
   each accepted (or blocked/awaiting-human with a recorded reason) → execute the
   terminal `gate-flip` as one final commit, `state: stopped (success)`,
   `STUTTER_LOOP: STOP (probes PASS x2 with core guards landed — gate flipped to hard)`.
2. **Lane-dry**: 2 consecutive no-accepts within a lane closes that lane; move to the
   next lane (do NOT global-stop).
3. **All lanes dry or awaiting-human** → `state: stopped (awaiting-human)`; the STOP
   line names the open packets — a hand-off, not a failure.
4. **Cost caps** (§1.5) → `state: stopped (cost-cap)`.
5. Otherwise CONTINUE, naming the next fix-id.

## §10 Bench spec (what `q1` builds; the probes ARE the metric)

`scripts/stutter_bench.py` — hermetic, keyless, deterministic where possible; runs
via `make stutter`; writes `data/stutter/<utc-ts>.json`; exits 0 always (the JSON
carries pass/fail — soft gate until `gate-flip`).

```json
{
  "schema_version": 1,
  "timestamp_utc": "",
  "probes": {
    "echo_storm": {
      "echo_events_injected": 6,
      "echo_turns_opened": 0,
      "genuine_bargein_honored": true,
      "budget": {"echo_turns_opened": 0, "genuine_bargein_honored": true},
      "pass": true
    },
    "clear_accounting": {
      "clears_sent": 1,
      "genuine_interruptions": 1,
      "budget": {"excess_clears": 0},
      "pass": true
    },
    "phantom_tail": {
      "tail_echo_turns_opened": 0,
      "enforced": false,
      "budget": {"tail_echo_turns_opened": 0},
      "pass": true
    },
    "pacing": {
      "cadence_ms": 40,
      "runs": 3,
      "frame_interval_p95_ms": 0.0,
      "max_gap_ms_median": 0.0,
      "noise_pct": 0.0,
      "gaps_over_2x_cadence_median": 0,
      "budget": {"max_gap_ms_median": 120, "gaps_over_2x_cadence_median": 0},
      "pass": true
    }
  },
  "overall_pass": true
}
```

Probe construction (reuse the fakes and patterns already in `tests/voice/`):

- **echo_storm**: build the production guard via `_build_user_turn_strategies()`;
  drive `process_frame` with `BotStartedSpeakingFrame`, then 6 echo-shaped events
  (1–2-word `InterimTranscriptionFrame`/`TranscriptionFrame` — the documented
  hallucination shapes "Wow.", "watch.", "thank you"); count `on_user_turn_started`
  firings → `echo_turns_opened` (budget 0). Then one genuine 5-word transcription →
  `genuine_bargein_honored` must be true. Encodes the RCA and the
  anti-overcorrection invariant in one probe.
- **clear_accounting**: `SafeTwilioFrameSerializer` — one `InterruptionFrame` per
  genuine interruption from the storm scenario; `bargein_clears ==
  genuine_interruptions` (no phantom clears, none missing).
- **phantom_tail**: `BotStoppedSpeakingFrame`, then a 1-word transcription injected
  immediately (the trailing-echo window). `enforced: false` (advisory, still
  reported) until f1 lands; f1's commit flips `enforced` to true — from then on a
  tail echo opening a turn fails the bench. A 1-word transcription arriving AFTER
  the tail window must still open the turn (the caller's quick "yes" — assert it).
- **pacing**: instantiate `FastAPIWebsocketTransport` with a stub websocket recording
  `send` timestamps; push `StartFrame` (8 kHz in/out) + ~3 s of synthetic 8 kHz
  `OutputAudioRawFrame`s through `transport.output()`; compute inter-send intervals.
  Run 3×, report medians + `noise_pct`. Budgets deliberately generous (CI jitter):
  this probe exists to catch a *blocking regression* in the send path and to verify
  cadence after f2 (which updates `cadence_ms` 40→20 in the same commit).

`tests/test_stutter_bench.py` pins the schema (keys, budgets present, pass logic) and
runs the probe functions in-process so `make test` alone catches bench rot.
