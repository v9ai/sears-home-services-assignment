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
7. Per-turn latency logs captured and reported; p50 ≤ 2.5 s to first audio is the
   target until the DeepSeek latency decision either hardens or changes it.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; live-call checklist passed; PDF voice readiness
      transcript/eval evidence saved.
- [ ] Constitution updates (mission scope, tech-stack models/secrets, roadmap) shipped
      with this feature.
- [ ] Deferred scope (MMS, outbound, transfer, full-duplex) recorded in the backlog.
- [ ] Roadmap Phase 5 ticked `[x]`.
