# Twilio Telephony (Live Phone Channel) — Validation

## Automated
- [x] Webhook signature validation: unsigned/mis-signed requests rejected; signed
      request returns the `<Connect><Stream>` TwiML. `tests/phone/test_webhook.py`.
- [x] Codec round-trip: μ-law 8 kHz → PCM → μ-law byte-stable on fixtures.
      `tests/phone/test_codec.py`.
- [x] VAD endpointing unit tests against fixture audio (speech, silence, hangover).
      `tests/phone/test_vad.py`.
- [x] Bridge unit test: scripted `start`/`media`/`stop` sequence creates a
      `channel='phone'` session and produces outbound `media` frames.
      `tests/phone/test_routes.py` (`RecordingSessionRecorder` stands in for the real
      `sessions` repo per the COORDINATION §4 stub seam — see plan.md Integration
      delta 4).
- [ ] **Pending PDF voice readiness gate** — structural + judged evals green on a
      phone-channel transcript captured during the live-call checklist: needs the real
      agent + a completed live call (COORDINATION §5 step 5); not standalone-completable
      in this worktree. Required assertions: professional greeting/rapport,
      appliance/symptom/error-code capture, no re-ask of known facts during scheduling,
      safety interrupt, booking read-back, appointment persistence, STT→agent→TTS seam
      evidence, and first-audio latency reporting.
- [x] `make lint` + `make test` clean — verified directly (`ruff check`, `ruff format
      --check`, `pytest tests/phone`: 37 passed) since the Makefile `lint`/`test`
      target bodies are still testing-evals' stubs (plan.md Integration delta 2).
- [ ] **Integration suite** (`tests/phone/test_integration.py` — requirements
      § Integration tests, spec'd 2026-07-08, unimplemented) green:
      webhook⇄bridge contract coherence (TwiML stream path == mounted route;
      `<Parameter>` names == `customParameters` keys read) · full call over the
      mounted `/ws/twilio` with the production `PhoneCallRuntime` (greeting frames
      before caller speech; scripted speech → agent reply frames; clean stop) ·
      persistence integration (sessions row `channel='phone'`, `ts`/`audio_seq`
      transcript keys, caller+agent wavs under `RECORDINGS_DIR/{session_id}/`;
      skips loudly without Postgres, passes against the Compose db) · wire-level
      barge-in `{"event":"clear"}` for the bound streamSid · PUBLIC_HOST-signed
      webhook validation (proxy-fronted topology).
- [ ] **Twilio observability suite** green:
      scripted `start` → `media` → `stop` emits the required lifecycle events with
      `call_sid` / `stream_sid` / `session_id` correlation; invalid signature and
      missing-token webhook paths log typed safe events; barge-in logs
      `twilio.barge_in.clear_sent`; STT/TTS/agent/persist/recording failure tests log
      typed failure events without dropping the call where graceful degradation is
      specified; log capture asserts no raw media payloads, transcript text, phone
      numbers, signatures, auth tokens, API keys, DB URLs, emails, or upload links.
- [ ] **Latency trace assertions** green:
      per-turn logs include `eos_to_stt_ms`, `stt_to_agent_first_token_ms`,
      `agent_first_token_to_first_audio_ms`, `eos_to_first_audio_ms`, and
      `turn_total_ms`; call summary logs p50/p95 for first-audio latency.

- [x] **Phone-audio quality gate (2026-07-10, stutter-hardening loop)** — `make stutter`
      (hermetic, keyless, HARD gate wired into `make test`): echo-shaped transcriptions
      can't interrupt the speaking bot (barge-in echo loop, the RCA'd stutter cause) while
      a genuine ≥3-word talk-over still does; trailing echo after `BotStoppedSpeaking` is
      guarded for `VOICE_BARGEIN_TAIL_MS`; Twilio `clear`s == genuine interruptions; 20 ms
      Twilio-idiomatic outbound framing with paced cadence. Loop ledger + probe history:
      `specs/features/2026-07-10-stutter-hardening/loop-ledger.md`; live-evidence tooling:
      `scripts/call_audio_report.py`, `voice.bargein.storm` event, `barge_ins`/`bargein_storms`
      in `twilio.call.summary`.

- [x] **Synthetic-caller run (2026-07-08, hosted)** — a fake call driven end-to-end
      with an OpenAI-TTS caller voice over the real Media Streams protocol against the
      HOSTED `wss://…/ws/twilio`: greeting audio within 2.5 s of `start` · **barge-in
      `clear` events fired live** when the synthetic caller spoke over playback ·
      **real `gpt-4o-transcribe` correctly transcribed the synthetic voice** ("My
      washer is making a loud grinding noise." / "Showing error E3.") · agent
      identified `washer`, captured both symptoms, asked diagnostic follow-ups ·
      ~8 s of agent reply audio captured (μ-law → wav artifact) · session + transcript
      persisted to Neon and visible via the hosted recordings API. This is the PDF
      voice-readiness loop verified minus only the PSTN leg; the real-handset
      checklist below remains the final manual item. (Script: scratchpad
      `fake_call.py`; candidate for `twilio_debug simulate --media`, see the
      twilio-cli-debug spec.)

## Manual — live-call checklist
1. Call the Twilio number (`+1 (318) 646-8479`) → greeting audio within ~2 s of answer
   (on a trial Twilio account, this timing starts after Twilio's own disclaimer message
   plays — expected, not a failure).
2. Speak "my refrigerator stopped cooling yesterday" → correct appliance + symptom in
   the case file; troubleshooting steps spoken back.
3. Interrupt the agent mid-sentence → playback stops (barge-in), agent yields the turn.
4. Say "I smell gas" → safety interrupt script, no further DIY steps.
5. Book a technician end-to-end by voice: zip → offered slots → read-back → yes →
   spoken confirmation; `appointments` row present, slot `booked`.
6. Continue the same call after booking facts are known → agent must not re-ask zip,
   appliance type, or selected time slot.
7. Per-turn latency logs captured and reported; the phone e2e p50 budget
   (`specs/latency/budgets.md`) is the target until the DeepSeek latency decision
   either hardens or changes it.
8. Trace audit: grep one live call by `call_sid` and `session_id`; confirm ordered
   events from webhook → stream start → greeting → VAD/STT/agent/TTS → first audio →
   stop/summary, including a p50/p95 call summary and no raw PII/secrets.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; live-call checklist passed; PDF voice readiness
      transcript/eval evidence saved.
- [ ] Twilio trace evidence saved for one live call and reviewed for event ordering,
      latency fields, failure taxonomy coverage, and redaction compliance.
- [ ] Constitution updates (mission scope, tech-stack models/secrets, roadmap) shipped
      with this feature.
- [ ] Deferred scope (MMS, outbound, transfer, full-duplex) recorded in the backlog.
- [ ] Roadmap Phase 5 ticked `[x]`.
