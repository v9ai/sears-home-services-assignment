# Twilio Telephony (Live Phone Channel) — Requirements

> **Superseded 2026-07-09.** The hand-rolled Twilio media bridge described by this spec
> (µ-law codec, RMS VAD, `TwilioMediaBridge`, batch `gpt-4o-transcribe` STT, the
> `start`/`media`/`stop` loop, the `clear` barge-in) was replaced by the Pipecat voice
> pipeline in `specs/features/2026-07-09-pipecat-voice-port/`. What REMAINS the scope of
> this spec is the Twilio **PSTN ingress** — the `POST /twilio/voice` webhook, the
> `<Connect><Stream>` TwiML, `X-Twilio-Signature` validation, the Twilio REST client, and
> number provisioning — all retained unchanged. For the media pipeline (transport, VAD,
> STT, LLM, TTS, barge-in) read `2026-07-09-pipecat-voice-port/{requirements,plan,validation}.md`.
> The RCA at the bottom is kept as **historical** rationale for the port.

## Source
Roadmap Phase 5 (specs/constitution/roadmap.md). Assignment Tier 1 "inbound call
handling" + deliverable "a functioning phone number we can call". User directive
(2026-07-08): telephony provider = **Twilio**. The media-pipeline Decisions (1–3) and
§ Contract shapes below were superseded 2026-07-09 by
`2026-07-09-pipecat-voice-port/` (Roadmap Phase 10).

## Scope

### Included (retained PSTN ingress)
- Inbound call webhook `POST /twilio/voice` (`app/phone/webhook.py`): answers with TwiML
  `<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio"/></Connect>` (`app/phone/twiml.py`).
- `X-Twilio-Signature` validation on the webhook (`app/phone/signature.py`, Decision 6:
  Account Auth Token only); unsigned/mis-signed requests rejected.
- Twilio REST client (`app/phone/twilio_client.py`) and number provisioning/console wiring.
- Sessions created with `channel='phone'`; caller number from Twilio captured (logged;
  the frozen `CaseFile.customer` contract has no phone field — see plan Integration deltas).

### Superseded 2026-07-09 (moved to the Pipecat pipeline)
The audio-facing media loop below was **replaced** by
`2026-07-09-pipecat-voice-port/` — read that feature's requirements for the current
contract. Retained here only to record what changed:
- ~~Twilio Media Streams bridge `/ws/twilio`… adapted onto the same session bridge~~ →
  `/ws/twilio` is now `app/voice/routes.py` handing the socket to Pipecat's `run_bot`;
  the transport is Pipecat's `TwilioFrameSerializer` + `FastAPIWebsocketTransport`.
- ~~Codec/resample adapter (μ-law 8 kHz ⇄ PCM)~~ → the serializer handles µ-law <-> PCM;
  the pipeline runs 8 kHz end-to-end.
- ~~STT = `gpt-4o-transcribe` turn-buffered + server-side VAD (~300 ms hangover)~~ →
  **Deepgram** streaming STT (default; `STT_PROVIDER=openai` swaps back to
  `gpt-4o-transcribe`/`whisper-1`) after a Silero `VADProcessor`.
- ~~TTS re-encoded to μ-law 8 kHz, 20 ms frames~~ → OpenAI `gpt-4o-mini-tts` (default;
  `TTS_PROVIDER` swaps to Cartesia / Deepgram Aura-2) through the serializer.
- ~~Basic barge-in via Twilio `clear`~~ → Pipecat native interruptions.
- **Structured Twilio observability**: every call emits correlated, privacy-safe
  lifecycle logs and per-turn latency traces to stdout/stderr. No external tracing
  backend is required for the take-home; the contract is stable structured key/value
  log events that can be grepped by `call_sid`, `stream_sid`, or `session_id`.
- Exposure: hosted, the Cloudflare Containers backend URL serves the webhook + WSS
  bridge directly; for local dev, an ngrok service in Compose (profile `phone`). Live
  number configured in the Twilio console pointing at the webhook.

### Not included (deferred)
- MMS image ingestion (Tier 3 stays on the email link) — backlog.
- Outbound calls, SMS confirmations, call transfer to humans — backlog.
- Full-duplex/overlapping speech beyond basic barge-in.

### Contract shapes
- Retained ingress handshake: the webhook returns `<Connect><Stream>` TwiML whose
  `<Stream url>` MUST equal the mounted `/ws/twilio` route, carrying `<Parameter>`
  customParameters (`CallSid`, `From`, `To`); on connect Twilio sends `connected` then a
  `start` message carrying `streamSid`/`callSid` — `app/voice/routes.py` reads those and
  hands off to `run_bot`. This handshake is the surviving contract this spec guarantees.
- **Superseded 2026-07-09**: ~~Twilio Media Streams `start`/`media`/`stop` wire framing
  (b64 μ-law 8 kHz) + server-sent `media`/`clear`~~ is now Pipecat's `TwilioFrameSerializer`
  concern (see `2026-07-09-pipecat-voice-port/`).
- **Superseded 2026-07-09**: ~~the shared `SessionBridge` interface
  (`receive_user_utterance` / `emit_transcript` / `emit_audio`)~~ is no longer the phone
  abstraction — Pipecat owns the phone media plane. `SessionBridge` still describes the web
  channel (`/ws/call`, `app/ws/routes.py`), which is untouched.
- Latency budget end-of-speech → first audio: p50 ≤ 2.5 s, p95 ≤ 4 s (STT 400–900 ms +
  first agent sentence 600–1500 ms + first TTS chunk 300–500 ms). Carried forward; now
  measured inside the Pipecat pipeline (metrics enabled) rather than the deleted bridge.
- Env: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`,
  `PUBLIC_HOST`, `NGROK_AUTHTOKEN`.
- Number provisioning: the Twilio number is acquired via the CLI (`twilio
  api:core:incoming-phone-numbers:create --phone-number=<E.164>`; the `twilio-cli`
  6.2.4 alias `phone-numbers:buy:local` does not exist and silently no-ops) or a
  console purchase before the webhook is wired up (plan group 4); trial accounts
  include one number at no cost.
- **Provisioned number**: `+13186468479` ((318) 646-8479, Louisiana), number SID
  `PN356e3d2a44afd34496997e66fb547da2` (twilio-cli profile `vadim`; the account SID
  lives in `.env` only, per mission non-negotiable 5). Still pointed at Twilio's demo
  webhook — voice/SMS URLs are rewired to `{PUBLIC_HOST}/twilio/voice` in plan group 4.
- Gates: `make test` (adapter/codec/VAD units), webhook signature validation test,
  manual live-call checklist.

### Observability contract

All Twilio-ingress logs MUST be structured key/value records under the existing
`app.phone*`/`app.voice*` loggers. Event names are stable API for operations and tests;
message text can change, field names cannot without updating this spec and tests. The
per-turn media/VAD/STT/LLM/TTS events below are now emitted by the Pipecat pipeline
(Pipecat traces + metrics — see `2026-07-09-pipecat-voice-port/`); the webhook and
`/ws/twilio` handshake events remain owned here.

#### Correlation fields
- Required when known: `event`, `session_id`, `call_sid`, `stream_sid`, `turn_index`.
- Required hashed PII fields when source data exists: `from_hash`, `to_hash`; optional
  `from_last4`, `to_last4` only when useful for manual Twilio-console matching.
- Component fields: `component=webhook|media_stream|vad|stt|agent|tts|bridge|
  recorder|latency`, `channel=phone`, `provider=twilio`. **Superseded 2026-07-09**: the
  `vad`/`stt`/`tts`/`bridge` components named the deleted media loop; those turn events now
  originate in the Pipecat pipeline.
- The retained webhook/route bind their log context via `app.obs.bind_call_context`
  (`call_sid`, `session_id`). **Superseded 2026-07-09**: ~~`PhoneCallContext` as the
  bridge/real-agent/recorder trace source~~ — that context object was deleted with the bridge.

#### Required lifecycle events
> **Superseded 2026-07-09** for the media/VAD/STT/agent/TTS/barge-in rows: those per-turn
> events are now emitted by the Pipecat pipeline (see `2026-07-09-pipecat-voice-port/`), not
> the deleted bridge. The webhook, stream lifecycle (accept/start/stop/disconnect), session,
> and greeting rows remain owned by the retained ingress + the Pipecat route.
- Webhook: `twilio.webhook.received`, `twilio.webhook.accepted`,
  `twilio.webhook.rejected`, `twilio.webhook.misconfigured`.
- Stream: `twilio.stream.accepted`, `twilio.stream.start`, `twilio.stream.stop`,
  `twilio.stream.disconnect`, `twilio.stream.malformed_frame`.
- Session: `twilio.session.created`, `twilio.session.ended`,
  `twilio.session.persist_failed`.
- Greeting: `twilio.greeting.started`, `twilio.greeting.completed`.
- Media/VAD: aggregate frame counters only via `twilio.media.summary`;
  `twilio.vad.speech_started`, `twilio.vad.speech_ended`.
- STT: `twilio.stt.started`, `twilio.stt.completed`, `twilio.stt.failed`.
- Agent/tools: `twilio.agent.turn_started`, `twilio.agent.tool_invoked` (tool name
  only), `twilio.agent.turn_completed`, `twilio.agent.turn_failed`.
- TTS/outbound: `twilio.tts.started`, `twilio.tts.completed`, `twilio.tts.failed`,
  `twilio.audio.first_frame_sent`, `twilio.barge_in.clear_sent`.
- Recording: `twilio.recording.caller_saved`, `twilio.recording.agent_saved`,
  `twilio.recording.write_failed`.
- Call summary: `twilio.call.summary` at normal stop or disconnect, with frame counts,
  turn count, barge-in count, recording counts, p50/p95 latency, and final status.

#### Latency fields
Each caller turn records monotonic durations in milliseconds:
`eos_to_stt_ms`, `stt_to_agent_first_token_ms`, `agent_first_token_to_first_audio_ms`,
`eos_to_first_audio_ms`, `turn_total_ms`. Call summary logs p50/p95 for
`eos_to_first_audio_ms`.

#### Redaction rules
Do not log raw phone numbers, `X-Twilio-Signature`, `TWILIO_AUTH_TOKEN`, ngrok tokens,
OpenAI/DeepSeek keys, DB URLs, media payloads, transcript text, upload links, email
addresses, or full exception payloads that can contain those values. Log exception
class + typed failure event + correlation fields; stack traces are allowed only after
the message has been sanitized and must not include request bodies/media payloads.

#### Failure taxonomy
Every non-happy path maps to one typed event and a final call status:
`invalid_signature`, `missing_config`, `caller_hangup`, `twilio_disconnect`,
`malformed_frame`, `stt_failed`, `agent_failed`, `tts_failed`, `db_persist_failed`,
`recording_write_failed`, `unexpected_exception`.

### Integration tests

Two surviving ingress items stay here; the full-call / barge-in / persistence items
below were **superseded 2026-07-09** — the mounted-`/ws/twilio` call, the agent tool
loop, and per-turn media assertions now live in the Pipecat pipeline's `tests/voice/`
suite (see `2026-07-09-pipecat-voice-port/{plan,validation}.md`).

Retained (the webhook/TwiML/signature seams survive):
1. **Webhook ⇄ stream contract coherence** — signed `POST /twilio/voice` on the full
   app → parse the returned TwiML: the `<Stream url>` path MUST equal the actually
   mounted `/ws/twilio` route path (now `app/voice/routes.py`), and the `<Parameter>`
   names (`CallSid`, `From`, `To`) MUST match the keys the route reads from
   `customParameters`. Catches silent drift between `twiml.py` and the WS route.
2. **Proxy-fronted signature validation** — a request signed against
   `https://{PUBLIC_HOST}/twilio/voice` validates even when the ASGI request's own
   host differs (the `_webhook_url` PUBLIC_HOST branch — exactly the ngrok/Cloudflare
   topology in production).

**Superseded 2026-07-09** (moved to `tests/voice/`, driven against the Pipecat pipeline):
- ~~Full call over the mounted WS with the production `PhoneCallRuntime` + `RealAgent` +
  `run_turn` tool loop, greeting-before-speech, scripted μ-law tone turn → agent reply
  frames~~ → `tests/voice/test_voice_routes.py` (`/ws/twilio` start parsing) +
  `test_voice_bot.py` (pipeline assembly) + `test_voice_port.py` (tool/guardrail parity).
- ~~Barge-in over the wire (`bridge.is_playing`, outbound `{"event":"clear"}`)~~ → Pipecat
  native interruptions; no hand-sent `clear`.
- ~~Persistence integration (`PhoneCallRuntime` writing `sessions`/recordings)~~ → Pipecat
  owns per-call memory; cross-call Postgres persistence is a deferred follow-up (see the
  port's Not-included scope).
- ~~`FakeTwilioWebSocket` / `handle_twilio_media_stream` unit driver, codec round-trips,
  RMS VAD, no-speech calls~~ → deleted with `app/phone/{routes,bridge,codec,vad}.py`.

Non-goals: live-network Twilio calls (that's the manual live-call checklist).

## Decisions
Decisions 1–3 were **superseded 2026-07-09** by
`2026-07-09-pipecat-voice-port/` Decisions 1–6 (Pipecat pipeline over the hand-rolled
bridge; Twilio serializer + FastAPI WS transport; Silero VAD; Deepgram STT; swappable
TTS; voice LLM `gpt-4o`). Original text kept struck through for the audit trail:

1. ~~**Twilio Programmable Voice + Media Streams over `<Gather>`/`<Say>`**~~ — Media Streams
   gives raw audio, keeping the STT/TTS seams and the agent in the loop; `<Gather>`/`<Say>`
   would replace both with Twilio's models. **Still true** (Twilio remains the PSTN carrier
   and Media Streams remain the transport) — but the audio is now consumed by Pipecat's
   `TwilioFrameSerializer`, not the deleted codec/bridge.
2. ~~**Adapter over rewrite** — a second implementation of the Phase 1 session-bridge
   interface~~ → **superseded**: replaced by a Pipecat pipeline (port Decision 1); the
   `SessionBridge` interface is no longer the phone abstraction.
3. ~~**STT = `gpt-4o-transcribe`, turn-based with server-side VAD**~~ → **superseded**:
   **Deepgram** streaming STT (default) after a Silero `VADProcessor` (port Decisions 3–4);
   `STT_PROVIDER=openai` swaps `gpt-4o-transcribe` back. OpenAI Realtime API still rejected.
4. **Webhook security** — validate `X-Twilio-Signature` on `/twilio/voice`; reject
   unsigned requests.
5. **Deploy path**: `make up` + Compose `phone` profile (ngrok) for dev; live number in
   the Twilio console. **Gate path**: unit gates + the manual live-call checklist.
6. **Auth Token for signature validation, not API Key** — `TWILIO_AUTH_TOKEN` must be
   the Account Auth Token (Console → Account Info), never an API Key secret; Twilio's
   `X-Twilio-Signature` algorithm is keyed to the Auth Token specifically. No outbound
   Twilio REST calls are in scope this phase, so no API Key/Secret env vars are needed.

## Architecture impact
- Adds the phone adapter plane and activates the STT model row in `tech-stack.md`.
  **Constitution-revising**: mission scope (live phone channel in scope), tech-stack
  models/secrets/forbidden-patterns, roadmap phases — updated alongside this spec
  (2026-07-08).
- **Superseded 2026-07-09**: the phone media plane moved from `app/phone` (deleted
  codec/VAD/bridge/routes/real_agent/fake_agent/call_context) to the Pipecat package
  `app/voice/`; `tech-stack.md` STT row → Deepgram, Roadmap Phase 5 → superseded by
  Phase 10. See `2026-07-09-pipecat-voice-port/` § Architecture impact.

## Parallel execution (COORDINATION.md §3–4)
- Owned paths (retained): `app/phone/{webhook,twiml,signature,twilio_client}.py` — the
  PSTN ingress. **Superseded 2026-07-09**: ~~`app/phone/{codec,vad,bridge,routes}.py`~~
  deleted; the media pipeline lives in `app/voice/` (owned by the port).
- **Superseded 2026-07-09**: ~~stub seam against the frozen `SessionBridge` with a
  `FakeAgent`; codec/VAD on fixture audio~~ — the Pipecat pipeline replaces the bridge and
  its stub seam (see the port's offline `tests/voice/` + `app/voice/verify_tools.py`).

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; the retained ingress builds on
  the webhook/TwiML/signature seams. **Superseded 2026-07-09**: ~~builds on the Phase 1 WS
  bridge and sentence-chunked TTS~~ — the media path is now the Pipecat pipeline.
- Constraints: mission non-negotiables (safety interrupt and never-re-ask apply verbatim
  on the phone channel — now structurally enforced by the Pipecat `SafetyGateProcessor` and
  `SystemPromptRefreshProcessor`, see the port); no other telephony provider SDKs (Twilio
  remains the sole PSTN carrier; Deepgram is a media, not PSTN, provider).
- Open questions (deferred): browser-mic STT loop for the web client — backlog, the
  phone channel makes it optional; answering-machine detection — backlog.
- Trial-account caveat: calls on a Twilio trial account play a spoken disclaimer before
  the `<Connect><Stream>` TwiML executes, adding latency ahead of the app's own
  greeting. This is expected trial behavior, not a defect — call it out explicitly
  rather than letting it silently read as a live-call checklist failure.

## Premature call-end RCA (2026-07-09 — measured, fixed)

(Historical — the bridge described here was replaced by the Pipecat pipeline, 2026-07-09;
kept as the rationale for the port. The measurements below are preserved verbatim.)

Symptom: live calls died at ~14 s (two consecutive calls, identical duration), right
after the caller's first utterance. No Twilio-side alerts — the stream closed from
our side, and with `<Connect><Stream>` a closed stream ends the call.

**Root cause (reproduced in-suite, then fixed):** `aadaa92` (trace instrumentation)
changed the bridge to call `agent.handle_turn(text, self, audio_seq=…, trace=…)` and
updated `FakeAgent` — but NOT `RealAgent`. Every production turn raised `TypeError`
immediately after STT; the exception unwound the `/ws/twilio` message loop; the WS
closed; Twilio ended the call. Timeline fit: greeting ~10 s (live-synth — see
contributing cause 2) + utterance + VAD close + STT ≈ 14 s.

Contributing causes found on the same investigation:
1. **No exception containment in the message loop** — `transcribe`, `greet`,
   `start_session`, and turn processing were all unwrapped: ANY per-call failure
   (an STT hiccup, a DB blip at answer) ended the whole call. Fixed (F3): every
   per-call step degrades that step only; the loop always reaches its natural stop.
2. **Container data dirs unwritable** (`/app/data` never created; non-root user) —
   the P0-1 TTS cache silently never worked hosted (PermissionError on every write,
   reproduced in the local container): every greeting/filler re-synthesized live.
   Recordings and uploads writes equally dead. Fixed: Dockerfile creates + chowns
   `data/{uploads,recordings,tts_cache}`.
3. **Read-starvation (F2, structural)** — turn processing was awaited INLINE in the
   message loop: inbound frames unread for the whole turn (barge-in dead during
   agent speech, Twilio backpressure). Fixed: turns run as chained tasks; the loop
   never stops reading; barge-in now works mid-reply.
4. **Container stdout was dropped** (no `[observability]`) — the crash was
   undiagnosable from `wrangler tail`. Fixed: observability enabled.
5. `SpeechPipeline.drain()` could re-raise a mid-emission socket error into the
   caller. Fixed: emit failures are contained per-sentence; `drain()` never raises.

Regression guards (`tests/phone/test_call_survival.py`): STT-failure survival,
greet/DB-failure-at-answer survival, reader-not-blocked-by-slow-turn, and the
**bridge↔agent call-contract signature guard** that would have caught the root cause
at commit time (`handle_turn` must accept `audio_seq` and `trace` on every
implementation).

Deploy note: a `wrangler deploy` restarts the container DO and kills any live call
(`1012 service restart`) — never deploy during a live-testing window.
