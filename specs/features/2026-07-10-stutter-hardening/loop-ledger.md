# Stutter Loop Ledger
state: running
iteration: 5
judged_eval_runs_total: 3
consecutive_all_pass: 5
lane_no_accepts: {Q: 0, F: 0}
known_failing_tests: none (tests/scheduling/test_booking.py flaked in i3's full run only; clean in i4's full run and 2x in isolation — collaborator-owned, booking loop active there)

Protocol: `loop-protocol.md` (committed copy of `.claude/skills/stutter-iterate/SKILL.md`;
on drift the committed copy wins). Reports in `data/stutter/` (gitignored, referenced by
filename). Target defect: the 2026-07-09 barge-in echo loop
(docs/local-twilio-run.md "Stuttering during the reply").

## Iteration 5 — f2 — ACCEPTED

```json
{
  "iteration": 5,
  "timestamp_utc": "2026-07-10T06:18:08Z",
  "lane": "F",
  "fix_id": "f2",
  "description": "Twilio-idiomatic 20 ms framing: new app/voice/bot.py::_build_transport_params sets audio_out_10ms_chunks=VOICE_OUT_10MS_CHUNKS (default 2; pipecat default was 4 = 40 ms bursts). run_bot AND the bench's pacing probe build params through the same function, so bench and production framing cannot drift. Bench budget now pins cadence_ms=20. 3 new tests (tests/voice/test_out_chunks.py); .env.example documents the knob.",
  "baseline_report": "20260710T060215Z.json",
  "after_report": "20260710T061808Z.json",
  "target_probe": "pacing",
  "probes_delta": {
    "pacing": "cadence_ms 40 -> 20 (structural, budget-pinned); max_gap_ms_median 42.31 -> 22.63; frame_interval_p95 41.56 -> 21.63; gaps_over_2x_cadence_median 0 even at the tighter 40 ms threshold",
    "echo_storm": "unchanged PASS (genuine_bargein_honored true)",
    "clear_accounting": "unchanged PASS",
    "phantom_tail": "unchanged PASS (enforced)"
  },
  "pacing_noise_pct": 49.3,
  "live_evidence": null,
  "collaborator_dirty_files": [],
  "gates": {
    "lint": "PASS",
    "test": "PASS (641 passed, 0 failed — full suite)",
    "eval": "PASS (make eval-hermetic: 37 passed, 2 deselected — mandatory lane F)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i5: f2 (git log --grep)",
  "revert_commit": null,
  "notes": "pacing_noise_pct 49.3 looks high but is relative to a tiny absolute value (max gaps 20-30 ms range at 20 ms cadence); the absolute budget (120 ms) is what gates. Latency note (§0.3): finer framing halves per-message payload, no measurable latency-path change expected; latency loop's bench does not cover the phone wire leg (its q0-4 pending), nothing to flag. f3 remains evidence-gated and there is NO gap evidence (0 gaps over 2x cadence, no live analyzer verdicts) — f3 will not run without evidence. §9.1 success condition now met: checking after this record."
}
```

## Iteration 4 — f1 — ACCEPTED

```json
{
  "iteration": 4,
  "timestamp_utc": "2026-07-10T06:02:15Z",
  "lane": "F",
  "fix_id": "f1",
  "description": "Echo-tail guard: app/voice/turn_guard.py::EchoTailMinWordsStrategy keeps the min-words bar up for VOICE_BARGEIN_TAIL_MS (default 400) after BotStoppedSpeakingFrame — the trailing-echo window from the phantom-turns incident. Injectable clock for tests; factory wires it by default, VOICE_BARGEIN_TAIL_MS=0 reverts to plain MinWords. Bench phantom_tail probe now ENFORCED with a post-window anti-overcorrection assertion. 10 new tests (tests/voice/test_echo_tail_guard.py); .env.example documents the knob.",
  "baseline_report": "20260710T054143Z.json",
  "after_report": "20260710T060215Z.json",
  "target_probe": "phantom_tail",
  "probes_delta": {
    "phantom_tail": "tail_echo_turns_opened 1 -> 0, enforced false -> true, post_window_turn_opened true (the measured i1 defect is closed and now gated)",
    "echo_storm": "unchanged PASS — genuine_bargein_honored stayed true (§0.1 invariant)",
    "clear_accounting": "unchanged PASS",
    "pacing": "unchanged PASS (cadence 40ms)"
  },
  "pacing_noise_pct": 2.7,
  "live_evidence": null,
  "collaborator_dirty_files": ["evals/adaptive_driver.py", "tests/test_booking_quality_policy.py", "tests/voice/test_bargein_guard.py (import cosmetics — I edited one test in this file for the f1 semantics change; their pending cosmetic reorder rides along in this commit, disclosed here)"],
  "gates": {
    "lint": "PASS",
    "test": "PASS (636 passed, 0 failed — full suite)",
    "eval": "PASS (make eval-hermetic: 37 passed, 2 deselected — mandatory lane F)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i4: f1 (git log --grep)",
  "revert_commit": null,
  "notes": "Semantics change pinned: test_bargein_guard.py::test_single_word_opens_turn_when_bot_is_silent now runs with VOICE_BARGEIN_TAIL_MS=0 (its historical premise); the default-tail behavior lives in test_echo_tail_guard.py (in-tail fragment blocked; >= min_words INSIDE the tail still opens — the guard raises the word bar, never mutes; 1-word opens after the window; reset clears tail). KNOWN TRADE-OFF for h2's packet: a caller's lone one-word answer landing < 400 ms after the bot stops is suppressed until the window passes — rare on real PSTN (STT finals usually arrive later) but it is the cost side of the tail. Subclass couples to pipecat 1.5 privates (_bot_speaking); test_echo_tail_guard.py pins the contract. Next: f2 (20 ms Twilio framing)."
}
```

## Iteration 3 — q3 — ACCEPTED

```json
{
  "iteration": 3,
  "timestamp_utc": "2026-07-10T05:41:44Z",
  "lane": "Q",
  "fix_id": "q3",
  "description": "Barge-in storm tripwire: SafeTwilioFrameSerializer counts media frames between clears; a clear landing < STORM_CLEAR_WINDOW_FRAMES (25 ~= 1s at 40ms cadence) after the previous one increments storm_rapid_clears and logs voice.bargein.storm live. twilio.call.summary gains bargein_storms. 3 new tests in tests/voice/test_serializer.py (rapid re-clear trips + logs; spaced clears don't; first clear never does).",
  "baseline_report": "20260710T051740Z.json",
  "after_report": "20260710T054143Z.json",
  "target_probe": null,
  "probes_delta": {"all": "unchanged, all PASS; clear_accounting still exact with the storm logic in the same path"},
  "pacing_noise_pct": 2.7,
  "live_evidence": null,
  "collaborator_dirty_files": ["tests/voice/test_bargein_guard.py (import cosmetics)", "tests/test_booking_quality_policy.py"],
  "gates": {
    "lint": "PASS",
    "test": "PASS* (624 passed; tests/scheduling/test_booking.py flaked — different member per run, 2x clean in isolation; collaborator-owned per §6.2, not blocking)",
    "eval": "PASS (make eval-hermetic: 37 passed, 2 deselected — mandatory, app/voice touched)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i3: q3 (git log --grep)",
  "revert_commit": null,
  "notes": "DESIGN DEVIATION from the protocol sketch: the serializer never sees BotStartedSpeakingFrame (it only serializes wire-bound frames), so the 'within one reply' window is measured as outbound media frames between clears — a rapid re-clear (< ~1s of reply audio since the last clear) is the storm signature at the wire boundary. Same intent, actually observable. Lane Q complete (q1-q3). Next: f1 (echo-tail guard — the phantom_tail probe's measured 1 phantom turn is the target)."
}
```

## Iteration 2 — q2 — ACCEPTED

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-10T05:22:48Z",
  "lane": "Q",
  "fix_id": "q2",
  "description": "scripts/call_audio_report.py — offline stereo-WAV stutter analyzer (bot = right channel): mid-reply gaps > 250 ms, restart detection via normalized cross-correlation of the post-gap head against the pre-gap reply (up to 5 s back), per-call JSON verdict clean|stutter-suspect. tests/test_call_audio_report.py: 9 tests on synthetic seeded-noise WAVs (clean, gap, restart, non-restart gap, prosody pause, empty, right-channel isolation, dir scan, absence).",
  "baseline_report": "20260710T050440Z.json",
  "after_report": "20260710T051740Z.json",
  "target_probe": null,
  "probes_delta": {"all": "unchanged, all PASS (no app/voice code touched); pacing max_gap median 42.31 -> 40.71ms within noise"},
  "pacing_noise_pct": 2.7,
  "live_evidence": "analyzer run on data/recordings: calls_analyzed=0 (no call.wav yet — only per-line web-channel WAVs from 2026-07-08; evidence lane armed for the next real call)",
  "collaborator_dirty_files": ["evals/adaptive_driver.py", "evals/test_library_live.py", "pyproject.toml", "specs/features/2026-07-08-testing-evals/requirements.md", "tests/test_booking_quality_policy.py", "tests/voice/test_bargein_guard.py", "tests/test_eval_gate_split.py (untracked)"],
  "gates": {
    "lint": "PASS",
    "test": "PASS (618 passed, 0 failed — full suite; hermetic guard FILLER_ENABLED=0, 144 passed)",
    "eval": "SKIPPED (pure-harness lane-Q diff: analyzer script + its tests; no app/ code touched)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i2: q2 (git log --grep)",
  "revert_commit": null,
  "notes": "Restart detector v1 (tail-vs-head at the gap) was wrong — a restart replays from EARLIER in the reply, not the cut point; rewritten as post-gap-head searched across the pre-gap region with sliding-norm normalization (caught by the synthetic-restart test before commit). Next: q3 (storm tripwire log_event in the serializer — touches app/voice/serializer.py, eval-hermetic will be mandatory)."
}
```

## Iteration 1 — q1 — ACCEPTED

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-10T05:10:36Z",
  "lane": "Q",
  "fix_id": "q1",
  "description": "Build the hermetic stutter bench: scripts/stutter_bench.py (echo_storm / clear_accounting / phantom_tail / pacing probes), make stutter target, tests/test_stutter_bench.py (6 tests), ledger + committed protocol copy.",
  "baseline_report": null,
  "after_report": "20260710T050440Z.json",
  "target_probe": null,
  "probes_delta": {
    "echo_storm": "PASS (0/6 echo events opened a turn; genuine 5-word barge-in honored)",
    "clear_accounting": "PASS (clears == genuine interruptions)",
    "phantom_tail": "ADVISORY PASS — tail_echo_turns_opened=1 measured: a 1-word trailing echo right after BotStoppedSpeaking opens a phantom turn today. This is f1's quantified target.",
    "pacing": "PASS (cadence 40ms, max_gap median 42.31ms vs 120ms budget, noise 2.7%, 0 gaps >2x cadence)"
  },
  "pacing_noise_pct": 2.7,
  "live_evidence": null,
  "collaborator_dirty_files": ["tests/voice/test_bargein_guard.py (import-order cosmetics; not in q1 surface)"],
  "gates": {
    "lint": "PASS",
    "test": "PASS (602 passed, 0 failed — full suite; hermetic guard run with FILLER_ENABLED=0, 144 passed)",
    "eval": "SKIPPED (pure-harness lane-Q diff: bench script + Makefile target + bench tests + specs; no app/ code touched)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i1: q1 (git log --grep)",
  "revert_commit": null,
  "notes": "FINDING for a future lane item: run_bot's missing-Twilio-creds 'degraded mode' (app/voice/bot.py — logs twilio.serializer.autohangup_disabled and proceeds) would actually raise in pipecat 1.5: TwilioFrameSerializer validates call_sid/account_sid/auth_token at __init__ when auto_hang_up (default True). The bench works around it with InputParams(auto_hang_up=False). Production always has creds so it is latent, but the log line lies about the failure mode. Candidate: pass auto_hang_up=False explicitly when creds are missing. Also noted: the latency loop's q0-3 eval split (make eval-hermetic / eval-live) has landed — lane-F iterations use make eval-hermetic as the mandatory gate. Next: q2 (call_audio_report.py — offline stereo-WAV gap/restart analyzer)."
}
```
