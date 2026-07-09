# Twilio Telephony (Live Phone Channel) — Plan

> **Superseded 2026-07-09.** Groups 2, 3, 5b and the media-side Integration deltas below
> describe the hand-rolled bridge, which was replaced by the Pipecat pipeline in
> `specs/features/2026-07-09-pipecat-voice-port/plan.md`. Groups 1 (webhook/TwiML) and 4
> (number/exposure) survive. Struck-through items name deleted modules; see the port's plan
> for the current implementation.

Implement in dependency order; the media bridge (group 3) was the risky group — run it
alone and pause for review before going live.

## 1. Webhook + TwiML                                    [retained]
- [x] `POST /twilio/voice` returning `<Connect><Stream>` TwiML; `X-Twilio-Signature`
      validation; unit tests with recorded signed requests.
      `app/phone/webhook.py` (route), `app/phone/twiml.py` (TwiML builder),
      `app/phone/signature.py` (validation, Decision 6: Account Auth Token only) ·
      `tests/phone/test_webhook.py` (unsigned/mis-signed/wrong-token rejected 403,
      missing-config 500, signed request returns TwiML with caller `<Parameter>`s).

## 2. Codec + VAD                                        [SUPERSEDED 2026-07-09]
Replaced by Pipecat's `TwilioFrameSerializer` (µ-law <-> PCM) + a Silero `VADProcessor`
(see port plan groups 4 + Decisions 3–4). `app/phone/{codec,vad}.py` and
`tests/phone/test_{codec,vad}.py` were **deleted**.
- [~] ~~μ-law 8 kHz ⇄ PCM resample/encode helpers; 20 ms framing (`app/phone/codec.py`,
      stdlib `audioop`) · `tests/phone/test_codec.py`~~ → serializer handles µ-law; pipeline
      runs 8 kHz end-to-end.
- [~] ~~Server-side VAD endpointing (~300 ms hangover) — `app/phone/vad.py` (RMS
      `TurnSegmenter`) · `tests/phone/test_vad.py`~~ → Silero `VADProcessor` (new dependency,
      revising the old "no new VAD dependency" note).

## 3. Media Streams bridge                               [SUPERSEDED 2026-07-09]
Replaced by the Pipecat pipeline (`app/voice/`, port plan group 4). `/ws/twilio` is now
`app/voice/routes.py` → `run_bot`; `app/phone/{routes,bridge,fake_agent,call_context}.py`
and `tests/phone/test_{routes,bridge}.py` were **deleted** (`stt.py` retained).
- [~] ~~`/ws/twilio` `start`/`media`/`stop` handling + session creation
      (`app/phone/routes.py` + `call_context.py`)~~ → `app/voice/routes.py` reads
      `connected`/`start` and hands off to Pipecat's `run_bot`.
- [~] ~~Shared session-bridge wiring: buffered utterance → STT (`gpt-4o-transcribe`) →
      agent → sentence-chunked TTS → μ-law frames out (`app/phone/bridge.py`,
      `fake_agent.py`)~~ → Pipecat pipeline `transport → VAD → STT → SafetyGate →
      PromptRefresh → LLM (ported tools) → Sanitizer → TTS → transport`. `stt.py` retained.
- [~] ~~Barge-in via `TwilioMediaBridge.interrupt_playback()` + Twilio `clear`~~ → Pipecat
      native interruptions (no hand-sent `clear`).

## 4. Dev exposure + number                              [retained]
- [x] Provision the Twilio number: `+13186468479` ((318) 646-8479, Louisiana), SID
      `PN356e3d2a44afd34496997e66fb547da2`, via
      `twilio api:core:incoming-phone-numbers:create --phone-number=+13186468479`
      (`phone-numbers:buy:local` doesn't exist in `twilio-cli` 6.2.4).
- [x] Compose `phone` profile: ngrok service, `PUBLIC_HOST` wiring. Already present in
      the foundation-commit `docker-compose.yml` (`ngrok` service, `profiles: ["phone"]`,
      `env_file: .env` so `NGROK_AUTHTOKEN` reaches the image) — nothing to add; this
      feature does not own `docker-compose.yml` so no edit was made either way.
- [ ] **Pending, not standalone-completable**: Twilio console voice webhook →
      `{PUBLIC_HOST}/twilio/voice`, and documenting the setup steps in the README.
      Needs a live `PUBLIC_HOST` (a running `docker compose --profile phone up` tunnel,
      or the Cloudflare Containers deploy) that doesn't exist yet in this standalone
      worktree; README is owned by deployment-deliverables (Integration deltas below).

## 5. Latency instrumentation                            [partially superseded]
- [x] `app/phone/latency.py` (`LatencyRecorder`) retained. **Superseded 2026-07-09**: the
      end-of-speech → first-audio wiring into `TwilioMediaBridge` is gone; per-turn timings
      are now Pipecat pipeline metrics (`PipelineParams(enable_metrics=True)`), still
      compared against the same budget (p50 ≤ 2.5 s / p95 ≤ 4 s).
- [~] ~~Expand to full per-turn trace timings persisted in the in-memory call trace~~ →
      Pipecat metrics/traces cover the STT/LLM-first-token/TTS-first-audio seams.

## 5b. Structured Twilio observability (added 2026-07-08)   [partially superseded]
> **Superseded 2026-07-09** for the media/VAD/STT/agent/TTS/barge-in events (now Pipecat
> pipeline traces, see the port). The webhook + `/ws/twilio` handshake lifecycle events
> remain owned here; `PhoneCallContext`-threaded bridge/real-agent/recorder logging is gone
> (those modules were deleted). Remaining unimplemented sub-items below apply only to the
> retained ingress.
- [ ] Add a small `app/phone/observability.py` helper: stable event-name constants,
      `TwilioTraceContext` derived from `PhoneCallContext`, phone-number hash/last4
      helpers, and `log_twilio_event(logger, event, context, **fields)` that emits
      key/value logs without raw PII.
- [ ] Thread trace context through webhook, media-stream route, bridge, STT, real-agent,
      recorder, and latency code. `PhoneCallContext` remains the source of truth for
      `call_sid`, `stream_sid`, `session_id`, caller/called hashes, and turn counters.
- [ ] Emit lifecycle events required by `requirements.md`: webhook accepted/rejected,
      stream accepted/start/stop/disconnect, session create/end, greeting start/end,
      VAD speech start/end, STT start/end, agent turn/tool/failure, TTS start/end,
      first outbound audio, barge-in clear, recording save/failure, persist failure,
      malformed frame, and final call summary.
- [ ] Record aggregate media counters only: inbound frame count, outbound frame count,
      caller turns, agent turns, barge-in count, recording count, and dropped/malformed
      frame count. Never log raw Twilio `media.payload` or transcript text by default.
- [ ] Implement failure taxonomy mapping: invalid signature, missing config, caller
      hangup, Twilio disconnect, malformed frame, STT failed, agent failed, TTS failed,
      DB persist failed, recording write failed, unexpected exception.
- [ ] Tests: caplog assertions for happy call lifecycle ordering; invalid signature
      and missing config; barge-in `clear`; STT/TTS/agent/persist/recording failures;
      and a redaction test proving no phone number, signature, media payload, transcript
      text, API key shape, DB URL, email, or upload link appears in Twilio logs.

## 6. Gates
- [x] `make lint` + `make test` clean — the surviving `tests/phone/` units are
      webhook/signature/twiml/stt/latency. **Superseded 2026-07-09**: ~~codec/VAD/bridge/
      routes units~~ deleted; the pipeline gates are `tests/voice/` + `make eval-voice`
      (see the port's plan group 6–7 and validation).
- [ ] Twilio observability tests green, including redaction checks and call-summary
      latency fields.
- [ ] **Pending**: manual live-call checklist (validation.md) — needs the real agent
      (voice-diagnostic-core) and a live `PUBLIC_HOST`; per COORDINATION §5 step 5, this
      runs at integration, not in this standalone worktree.
- [ ] Roadmap Phase 5 left unticked in `specs/constitution/roadmap.md` until the
      live-call checklist above actually passes (its Definition of Done requires it).

## 7. Integration tests                                  [partially superseded]
- [x] Retained ingress coherence (per requirements § Integration tests): webhook⇄stream
      contract coherence (TwiML `<Stream url>` == mounted `/ws/twilio`; `<Parameter>`
      names == the keys `app/voice/routes.py` reads) + PUBLIC_HOST-signed webhook
      validation — driven against the surviving webhook/twiml/signature seams.
- [~] **Superseded 2026-07-09**: ~~full call over the mounted `/ws/twilio` with the
      production `PhoneCallRuntime`; persistence integration (sessions row + recordings);
      wire-level barge-in `clear`; `FakeTwilioWebSocket` / μ-law tone builders~~ → the
      Pipecat pipeline's `tests/voice/` (`test_voice_routes.py`, `test_voice_bot.py`,
      `test_voice_port.py`); cross-call persistence is a deferred follow-up (port scope).

## 8. Twilio-side call recording (added 2026-07-08, unimplemented)
- [ ] Start a dual-channel Twilio recording on call answer (REST, best-effort) and
      persist `sessions.call_sid` — owned jointly with call-recording-replay's
      Twilio-Recordings scope block; see that spec for the API/replay contract.

## Integration deltas

Shared files this feature needs but doesn't own (COORDINATION.md §3); the lead applies
these at merge time.

1. **`app/main.py`** — mount this feature's router. **APPLIED 2026-07-08** (lead,
   commit `771f496`): `phone_router` included alongside the ws + upload routers.
2. **`Makefile`** — `test`/`lint` bodies now run repo-wide (`pytest tests -q` picks up
   `tests/phone/` recursively; ruff runs on `.`). **APPLIED** via the testing-evals
   merge + the venv-aware `$(BIN)` fix; nothing phone-specific needed.
3. **Real agent adapter** — ~~**APPLIED 2026-07-08** (lead, commit `771f496`):
   `app/phone/real_agent.py` `RealAgent` wraps `app.agent.core.run_turn` +
   `app.agent.tts.synthesize(..., response_format="pcm")`; greeting-on-answer +
   per-turn spoken tool filler + failure fallback.~~ **SUPERSEDED 2026-07-09**:
   `real_agent.py`/`fake_agent.py` deleted — the Pipecat LLM service runs the tool loop
   directly over the ported tools (`app/voice/tools.py`), the greeting is a fixed
   `GREETING` spoken on `on_client_connected` (`app/voice/bot.py`), and tool-failure
   fallback is a spoken-safe string in each handler. See the port.
4. **Sessions-backed recorder** — ~~**APPLIED 2026-07-08** (lead, commit `771f496`):
   `PhoneCallRuntime` implements `SessionRecorder` against the real `sessions` repo
   (`channel='phone'`, per-turn `persist_session`), wired in
   `app/phone/routes.twilio_media_stream`.~~ **SUPERSEDED 2026-07-09**: `PhoneCallRuntime`
   deleted — Pipecat owns per-call memory (context aggregator + case-file-in-prompt);
   `book_appointment` runs inside the call session (`session.bind()`), closing the old
   `session_id=NULL` gap. Cross-call Postgres persistence is a deferred follow-up (port
   Not-included scope). The caller-number gap note still holds (frozen `CaseFile.customer`
   has no phone field).
5. **README.md** (owned by deployment-deliverables) — document the Twilio console
   webhook wiring step (plan group 4's pending item): number `+13186468479` → voice
   webhook `{PUBLIC_HOST}/twilio/voice`; `docker compose --profile phone up` for local
   ngrok exposure; trial-account disclaimer caveat (requirements.md "Context").
   **STILL PENDING** — lands together with the live-call checklist (needs a live
   `PUBLIC_HOST`).
