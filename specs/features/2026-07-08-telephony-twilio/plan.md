# Twilio Telephony (Live Phone Channel) — Plan

Implement in dependency order; the media bridge (group 3) is the risky group — run it
alone and pause for review before going live.

## 1. Webhook + TwiML
- [x] `POST /twilio/voice` returning `<Connect><Stream>` TwiML; `X-Twilio-Signature`
      validation; unit tests with recorded signed requests.
      `app/phone/webhook.py` (route), `app/phone/twiml.py` (TwiML builder),
      `app/phone/signature.py` (validation, Decision 6: Account Auth Token only) ·
      `tests/phone/test_webhook.py` (unsigned/mis-signed/wrong-token rejected 403,
      missing-config 500, signed request returns TwiML with caller `<Parameter>`s).

## 2. Codec + VAD
- [x] μ-law 8 kHz ⇄ PCM resample/encode helpers; 20 ms framing.
      `app/phone/codec.py` (stdlib `audioop`; safe while the project pins
      `python:3.12-slim`) · `tests/phone/test_codec.py` (round-trip, b64 framing,
      resample, silence).
- [x] Server-side VAD endpointing (~300 ms hangover) over inbound frames; unit-tested
      against fixture audio.
      `app/phone/vad.py` (RMS energy `TurnSegmenter` — no new VAD dependency) ·
      `tests/phone/test_vad.py` (synthesized tone/silence fixture audio).

## 3. Media Streams bridge                             ⏸ review after this group
- [x] `/ws/twilio` endpoint: `start`/`media`/`stop` handling, session creation with
      `channel='phone'`, caller number capture.
      `app/phone/routes.py` + `app/phone/call_context.py` (`SessionRecorder` seam —
      see Integration deltas, real `sessions` table isn't this feature's to write).
- [x] Wire to the shared session-bridge interface: buffered utterance → STT
      (`gpt-4o-transcribe`) → agent → sentence-chunked TTS → μ-law frames out.
      `app/phone/bridge.py` (`TwilioMediaBridge` implements `SessionBridge`),
      `app/phone/stt.py` (`gpt-4o-transcribe`/`whisper-1` via env flag),
      `app/phone/fake_agent.py` (stub turn-driver, COORDINATION §4) ·
      `tests/phone/test_bridge.py`, `tests/phone/test_routes.py`, `tests/phone/test_stt.py`.
- [x] Barge-in: speech-during-playback sends `clear` and yields the turn.
      `TwilioMediaBridge.interrupt_playback()` — cancels queued frames + sends `clear`;
      only fires on an actual in-flight playback (no spurious `clear` spam) ·
      covered in `tests/phone/test_bridge.py`.

## 4. Dev exposure + number
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

## 5. Latency instrumentation
- [x] Log end-of-speech → first-audio per turn; compare against the phone e2e budget
      (`specs/latency/budgets.md`).
      `app/phone/latency.py` (`LatencyRecorder`, wired into
      `TwilioMediaBridge.mark_end_of_speech()` / first outbound frame) ·
      `tests/phone/test_latency.py`.
- [x] Expand from single first-audio samples to full per-turn trace timings — as-built
      via the Pipecat port: `app/voice/metrics.py::VoiceMetricsObserver` logs
      end-of-speech → first-audio per turn (`voice.metrics.latency`) plus Pipecat's
      per-service TTFB/TTFA and LLM/TTS usage metrics per processor
      (`voice.metrics.ttfb`/`ttfa`/`llm_usage`/`tts_usage`); stage budgets are pinned
      in `app/latency/budgets.py` (latency-centralization spec) and asserted by
      `tests/voice/test_voice_latency_e2e.py` + `tests/voice/test_voice_metrics.py`.

## 5b. Structured Twilio observability
> **As-built note (2026-07-09).** Written for the pre-Pipecat bridge
> (`PhoneCallContext`, `TwilioMediaBridge`, `real_agent` — all deleted by the port).
> The intent landed via the cross-cutting observability-tracing spec
> (`app/obs.py`: `log_event` + `bind_call_context`) and the Pipecat modules; items
> below are ticked against that equivalent, with the original wording preserved.
- [x] Event helper — as-built: `app/obs.py` (`log_event` key/value events,
      `bind_call_context` for `call_sid` correlation, no raw PII) instead of the
      planned `app/phone/observability.py`; used by webhook, routes, serializer,
      bot, metrics, and recording code.
- [x] Thread trace context — as-built: `bind_call_context(call_sid=…)` in the
      webhook; `call_sid`/`stream_sid` threaded through `run_bot` →
      `SafeTwilioFrameSerializer` / `VoiceSession.for_call(call_sid)`;
      `sessions.call_sid` persisted for DB correlation.
- [x] Lifecycle events — emitted across the stack: `twilio.webhook`
      (accepted/rejected + `signature_valid`), `twilio.ws.*` (handshake
      disconnect/no-start), `twilio.stream.start`, `voice.malformed_twilio_frame`,
      `twilio.serializer.autohangup_disabled`, `voice.metrics.*` (per-turn latency +
      per-service TTFB/usage), `voice.recording.saved`/`write_failed`/`stop_failed`/
      `persist_failed`, `voice.session_row.ensure_failed`, `twilio.pipeline.error`,
      and the final `twilio.call.summary` (added 2026-07-09).
- [x] Aggregate media counters only — `SafeTwilioFrameSerializer` counts
      inbound/outbound/malformed frames at the wire boundary (each message passes
      exactly once); measured turns + latency percentiles from `LatencyRecorder`;
      all folded into the end-of-call `twilio.call.summary` event. Raw
      `media.payload` is never logged (frame counts only).
- [x] Failure taxonomy — as-built as distinct event names rather than a mapping
      module: invalid signature / missing config (`twilio.webhook` +
      `phone_webhook_auth_token_missing`), disconnect
      (`twilio.ws.disconnected_during_handshake`), malformed frame
      (`voice.malformed_twilio_frame`), recording/persist failures
      (`voice.recording.*`, `voice.session_row.ensure_failed`), unexpected exception
      (`twilio.pipeline.error`, sanitized to the exception class).
- [x] Tests — as-built: `tests/voice/test_routes_handshake.py` (handshake
      containment incl. disconnect/no-start), `tests/voice/test_serializer.py`
      (malformed-frame drop, counters, payload-redaction), `tests/phone/test_webhook.py`
      (invalid signature / missing config), `tests/voice/test_voice_metrics.py`
      (latency events), `tests/voice/test_call_recording.py` (recording failures
      swallowed + logged). Events log exception class / counts only — no payload,
      signature, or full phone number (see the serializer redaction test).

## 6. Gates
- [x] `make lint` + `make test` clean (webhook, codec, VAD, bridge units) — run directly
      via `ruff check`/`ruff format --check`/`pytest tests/phone` (37 tests) since the
      `lint`/`test` Makefile target bodies are still testing-evals' TODO stubs; see
      Integration deltas.
- [x] Twilio observability tests green, including redaction checks and call-summary
      latency fields (2026-07-09: `tests/voice` + `tests/phone`, 125 passed — see the
      as-built mapping in group 5b).
- [ ] **Pending**: manual live-call checklist (validation.md) — needs the real agent
      (voice-diagnostic-core) and a live `PUBLIC_HOST`; per COORDINATION §5 step 5, this
      runs at integration, not in this standalone worktree.
- [ ] Roadmap Phase 5 left unticked in `specs/constitution/roadmap.md` until the
      live-call checklist above actually passes (its Definition of Done requires it).

## 7. Integration tests
> **As-built note (2026-07-09).** Specified against the deleted pre-Pipecat runtime
> (`PhoneCallRuntime`, `tests/phone/test_routes.py` fakes). Equivalent coverage
> exists against the shipped Pipecat pipeline; a literal
> `tests/phone/test_integration.py` was not created.
- [x] Coverage as-built: pipeline build + tool-registration with fake STT/LLM/TTS
      (`tests/voice/test_voice_port.py`, `test_llm_factory.py`), handshake/`/ws/twilio`
      containment (`tests/voice/test_routes_handshake.py`), e2e latency over a scripted
      pipeline (`tests/voice/test_voice_latency_e2e.py`), recording persistence with
      `RECORDINGS_DIR` → tmp (`tests/voice/test_call_recording.py`,
      `tests/test_ws_recording_hooks.py`), barge-in `clear` at the wire boundary
      (serializer `InterruptionFrame` → Twilio `clear`,
      `tests/voice/test_serializer.py`), and PUBLIC_HOST-signed webhook validation
      (`tests/phone/test_webhook.py` + `tests/test_twilio_debug.py` signing
      round-trips; proven live 2026-07-09 via `make phone-debug cmd="simulate"` → 200
      TwiML against the running app).
- [x] Gate: green in `make test` with no reachable Postgres AND against the Compose
      db (full suite green 2026-07-09).

## 8. Twilio-side call recording
- [x] Start a dual-channel Twilio recording on call answer and persist
      `sessions.call_sid` — landed: `app/phone/twiml.py` emits
      `<Start><Recording channels="dual"/></Start>` before `<Connect>` (verified live
      2026-07-09: 3 real dual-channel recordings listed via
      `make phone-debug cmd="recordings"`), consumed by
      `app/recordings/routes.py:/twilio-audio/{sid}` through
      `app/phone/twilio_client.py`; see call-recording-replay for the replay contract.

## Integration deltas

Shared files this feature needs but doesn't own (COORDINATION.md §3); the lead applies
these at merge time.

1. **`app/main.py`** — mount this feature's router. **APPLIED 2026-07-08** (lead,
   commit `771f496`): `phone_router` included alongside the ws + upload routers.
2. **`Makefile`** — `test`/`lint` bodies now run repo-wide (`pytest tests -q` picks up
   `tests/phone/` recursively; ruff runs on `.`). **APPLIED** via the testing-evals
   merge + the venv-aware `$(BIN)` fix; nothing phone-specific needed.
3. **Real agent adapter** — **APPLIED 2026-07-08** (lead, commit `771f496`):
   `app/phone/real_agent.py` `RealAgent` wraps `app.agent.core.run_turn` +
   `app.agent.tts.synthesize(..., response_format="pcm")` — OpenAI TTS's `pcm` format
   IS mono linear PCM16 @ 24 kHz, confirming the bridge's resample assumption with no
   decode step. Also adds greeting-on-answer (the agent speaks first: `RealAgent.greet`
   plays `prompts.GREETING` on the Media Streams `start` event) and per-turn spoken
   tool filler + failure fallback, mirroring the web channel.
4. **Sessions-backed recorder** — **APPLIED 2026-07-08** (lead, commit `771f496`):
   `PhoneCallRuntime` implements `SessionRecorder` against the real `sessions` repo
   (`channel='phone'`, `ended_at` on stop, per-turn `persist_session`), bound to the
   same `SessionState` the `RealAgent` uses; wired as the production default in
   `app/phone/routes.twilio_media_stream`. `InMemorySessionRecorder` remains the test
   seam. Note: caller number is logged, not written to the case file — the frozen
   `CaseFile.customer` contract has no phone field (recorded gap; extend the contract
   in a future revision if appointments need caller-number traceability).
5. **README.md** (owned by deployment-deliverables) — document the Twilio console
   webhook wiring step (plan group 4's pending item): number `+13186468479` → voice
   webhook `{PUBLIC_HOST}/twilio/voice`; `docker compose --profile phone up` for local
   ngrok exposure; trial-account disclaimer caveat (requirements.md "Context").
   **STILL PENDING** — lands together with the live-call checklist (needs a live
   `PUBLIC_HOST`).
