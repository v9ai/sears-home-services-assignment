# Twilio Telephony (Live Phone Channel) — Validation

> **Superseded 2026-07-09.** The codec/VAD/bridge/`PhoneCallRuntime` gates below were
> replaced by the Pipecat pipeline's `tests/voice/` + `make eval-voice` gates
> (`specs/features/2026-07-09-pipecat-voice-port/validation.md`). The webhook/signature/
> TwiML gates and the manual live-call checklist survive (the checklist steps carry
> forward). Struck-through items name deleted tests.

## Automated
- [x] Webhook signature validation: unsigned/mis-signed requests rejected; signed
      request returns the `<Connect><Stream>` TwiML. `tests/phone/test_webhook.py`. [retained]
- [~] **Superseded 2026-07-09**: ~~Codec round-trip (μ-law 8 kHz → PCM → μ-law byte-stable),
      `tests/phone/test_codec.py`~~ → deleted; the serializer handles µ-law (port pipeline).
- [~] **Superseded 2026-07-09**: ~~VAD endpointing unit tests, `tests/phone/test_vad.py`~~ →
      deleted; Silero `VADProcessor` covered by `tests/voice/test_voice_bot.py`.
- [~] **Superseded 2026-07-09**: ~~Bridge unit test (scripted `start`/`media`/`stop` →
      `channel='phone'` session + outbound `media` frames), `tests/phone/test_routes.py`~~ →
      deleted; `/ws/twilio` start parsing + pipeline assembly are in
      `tests/voice/{test_voice_routes,test_voice_bot}.py`.
- [x] **Pipecat pipeline gates** (see the port's validation): `make test` incl. `tests/voice/`
      (tool parity, safety-gate parity, schema parity, pipeline/provider selection,
      `/ws/twilio` route) + `python -m app.voice.verify_tools` + `make eval-voice`.
- [ ] **Pending PDF voice readiness gate** — structural + judged evals green on a
      phone-channel transcript captured during the live-call checklist: needs the real
      agent + a completed live call (COORDINATION §5 step 5); not standalone-completable
      in this worktree. Required assertions: professional greeting/rapport,
      appliance/symptom/error-code capture, no re-ask of known facts during scheduling,
      safety interrupt, booking read-back, appointment persistence, STT→agent→TTS seam
      evidence, and first-audio latency reporting.
- [x] `make lint` + `make test` clean — the surviving `tests/phone/` units
      (webhook/signature/twiml/stt/latency) plus the Pipecat `tests/voice/` suite pass
      (`ruff check`, `ruff format --check`, `pytest`). **Superseded 2026-07-09**: the old
      37-test phone count included the deleted codec/VAD/bridge/routes tests.
- [x] **Ingress integration** green (retained subset of requirements § Integration tests):
      webhook⇄stream contract coherence (TwiML `<Stream url>` == mounted `/ws/twilio`;
      `<Parameter>` names == the keys `app/voice/routes.py` reads) · PUBLIC_HOST-signed
      webhook validation (proxy-fronted topology).
- [~] **Superseded 2026-07-09**: ~~full call over the mounted `/ws/twilio` with the
      production `PhoneCallRuntime`; persistence integration; wire-level barge-in
      `{"event":"clear"}`~~ → moved to the Pipecat `tests/voice/` suite (see the port's
      validation); barge-in is now a Pipecat native interruption, and cross-call
      persistence is a deferred follow-up.
- [~] **Twilio observability suite** — **partially superseded 2026-07-09**: the webhook +
      `/ws/twilio` handshake lifecycle events + redaction/failure-taxonomy checks remain
      here; ~~the media/VAD/STT/agent/TTS/barge-in events and `twilio.barge_in.clear_sent`~~
      are now Pipecat pipeline traces (port).
- [~] **Latency trace assertions** — **superseded 2026-07-09**: ~~per-turn logs
      `eos_to_stt_ms` / `stt_to_agent_first_token_ms` / `agent_first_token_to_first_audio_ms`
      / `eos_to_first_audio_ms` / `turn_total_ms` from the bridge~~ → Pipecat pipeline
      metrics (`enable_metrics=True`), same p50/p95 first-audio budget.

- [x] **Synthetic-caller run (2026-07-08, hosted — historical)** — recorded against the
      old hand-rolled bridge; kept as evidence that the Media Streams protocol + PSTN
      ingress worked end-to-end. The pipeline it exercised (µ-law bridge, `gpt-4o-transcribe`
      STT, `clear` barge-in) was **replaced by the Pipecat pipeline 2026-07-09** — re-run
      against the port for a current artifact. A fake call driven with an OpenAI-TTS caller
      voice over the real Media Streams protocol against the HOSTED `wss://…/ws/twilio`:
      greeting audio within 2.5 s of `start` · **barge-in fired live** when the synthetic
      caller spoke over playback · **STT correctly transcribed the synthetic voice** ("My
      washer is making a loud grinding noise." / "Showing error E3.") · agent identified
      `washer`, captured both symptoms, asked diagnostic follow-ups · ~8 s of agent reply
      audio captured (μ-law → wav artifact) · session + transcript persisted to Neon and
      visible via the hosted recordings API. (Script: scratchpad `fake_call.py`.)

## Manual — live-call checklist
(The steps carry forward to the Pipecat pipeline; mechanism references updated for the
port — barge-in is now a Pipecat native interruption, STT defaults to Deepgram. Needs
`DEEPGRAM_API_KEY` + `OPENAI_API_KEY` + `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` +
`PUBLIC_HOST`.)
1. Call the Twilio number (`+1 (318) 646-8479`) → greeting audio within ~2 s of answer
   (on a trial Twilio account, this timing starts after Twilio's own disclaimer message
   plays — expected, not a failure).
2. Speak "my refrigerator stopped cooling yesterday" → correct appliance + symptom in
   the case file; troubleshooting steps spoken back.
3. Interrupt the agent mid-sentence → playback stops (Pipecat native barge-in), agent
   yields the turn.
4. Say "I smell gas" → safety interrupt script (`SafetyGateProcessor`), no further DIY steps.
5. Book a technician end-to-end by voice: zip → offered slots → read-back → yes →
   spoken confirmation; `appointments` row present, slot `booked`.
6. Continue the same call after booking facts are known → agent must not re-ask zip,
   appliance type, or selected time slot.
7. Per-turn latency logs captured and reported; p50 ≤ 2.5 s to first audio is the
   target until the DeepSeek latency decision either hardens or changes it.
8. Trace audit: grep one live call by `call_sid` and `session_id`; confirm ordered
   events from webhook → stream start → greeting → VAD/STT/agent/TTS → first audio →
   stop, including no raw PII/secrets. (Per-turn media/VAD/STT/TTS events + latency are now
   Pipecat pipeline traces/metrics — see the port.)

## Definition of done
- [x] Each retained "Included (PSTN ingress)" scope bullet in `requirements.md` is
      observably true (webhook/TwiML/signature/twilio_client). The media-pipeline DoD moved
      to `2026-07-09-pipecat-voice-port/validation.md`.
- [ ] Retained automated gates green (webhook/signature/twiml) + the Pipecat `tests/voice/`
      + `make eval-voice` gates; live-call checklist passed; PDF voice readiness evidence saved.
- [ ] Twilio trace evidence saved for one live call and reviewed for event ordering and
      redaction compliance (media/latency traces now via Pipecat metrics).
- [x] Constitution updates (mission scope, tech-stack models/secrets, roadmap) shipped
      with the original Phase 5 change; **superseded 2026-07-09** by the Phase 10
      constitution edits (Deepgram STT row, Phase 5 marked superseded — see the port).
- [x] Deferred scope (MMS, outbound, transfer, full-duplex) recorded in the backlog.
- [~] **Superseded 2026-07-09**: ~~Roadmap Phase 5 ticked `[x]`~~ → Phase 5 marked superseded
      by **Phase 10** (Pipecat voice port); the live-call/PDF-readiness manual gate remains
      credential-blocked and tracked.
