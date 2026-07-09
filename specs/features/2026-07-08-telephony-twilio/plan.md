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
- [ ] Expand from single first-audio samples to full per-turn trace timings:
      end-of-speech → STT complete, STT complete → agent first token, first token →
      first audio, end-of-speech → first audio, and total turn duration. Persist those
      fields in the in-memory call trace and log them on turn completion.

## 5b. Structured Twilio observability (added 2026-07-08, unimplemented)
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
- [x] `make lint` + `make test` clean (webhook, codec, VAD, bridge units) — run directly
      via `ruff check`/`ruff format --check`/`pytest tests/phone` (37 tests) since the
      `lint`/`test` Makefile target bodies are still testing-evals' TODO stubs; see
      Integration deltas.
- [ ] Twilio observability tests green, including redaction checks and call-summary
      latency fields.
- [ ] **Pending**: manual live-call checklist (validation.md) — needs the real agent
      (voice-diagnostic-core) and a live `PUBLIC_HOST`; per COORDINATION §5 step 5, this
      runs at integration, not in this standalone worktree.
- [ ] Roadmap Phase 5 left unticked in `specs/constitution/roadmap.md` until the
      live-call checklist above actually passes (its Definition of Done requires it).

## 7. Integration tests (added 2026-07-08, unimplemented)
- [ ] `tests/phone/test_integration.py` per requirements § Integration tests:
      webhook⇄bridge contract coherence · full call over the mounted `/ws/twilio`
      with the production `PhoneCallRuntime` (get_llm → `FakeFunctionCallingLLM`,
      `tts.synthesize` → fake PCM, `RECORDINGS_DIR` → tmp) · persistence integration
      (db_session skip semantics; sessions row + recordings wavs) · wire-level
      barge-in `clear` · PUBLIC_HOST-signed webhook validation.
- [ ] Reuse, don't duplicate: μ-law tone/silence builders + `FakeTwilioWebSocket`
      from `tests/phone/test_routes.py` (lift shared helpers into
      `tests/phone/helpers.py` if importing across test modules gets awkward).
- [ ] Gate: green in `make test` with no reachable Postgres (persistence test skips
      loudly) AND fully green against the Compose db on 5433.

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
