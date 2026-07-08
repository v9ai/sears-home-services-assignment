# Twilio Telephony (Live Phone Channel) — Requirements

## Source
Roadmap Phase 5 (specs/constitution/roadmap.md). Assignment Tier 1 "inbound call
handling" + deliverable "a functioning phone number we can call". User directive
(2026-07-08): telephony provider = **Twilio**.

## Scope

### Included
- Inbound call webhook `POST /twilio/voice`: answers with TwiML
  `<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio"/></Connect>`.
- Twilio Media Streams bridge `/ws/twilio`: bidirectional WS carrying base64 μ-law
  8 kHz frames, adapted onto the same session bridge the web client uses.
- Codec/resample adapter: μ-law 8 kHz ⇄ PCM for STT/TTS.
- **STT enters here** (the phone channel is audio-only): `gpt-4o-transcribe` on
  turn-buffered caller audio with server-side VAD endpointing (~300 ms hangover);
  `whisper-1` behind an env flag.
- TTS replies encoded back to μ-law 8 kHz and streamed to Twilio in 20 ms frames.
- Basic barge-in: on caller speech during agent playback, send Twilio `clear` to flush
  queued audio and yield the turn.
- Sessions created with `channel='phone'`; caller number from Twilio captured to the
  case file / customer record.
- Exposure: hosted, the Cloudflare Containers backend URL serves the webhook + WSS
  bridge directly; for local dev, an ngrok service in Compose (profile `phone`). Live
  number configured in the Twilio console pointing at the webhook.

### Not included (deferred)
- MMS image ingestion (Tier 3 stays on the email link) — backlog.
- Outbound calls, SMS confirmations, call transfer to humans — backlog.
- Full-duplex/overlapping speech beyond basic barge-in.

### Contract shapes
- Twilio Media Streams messages: `start` / `media` (`payload` = b64 μ-law 8 kHz) /
  `stop`; server sends `media` frames + `clear`.
- Session bridge interface (shared with `/ws/call`): `receive_user_utterance(text)` /
  `emit_transcript(role, text)` / `emit_audio(chunk)` — the phone adapter converts
  audio ⇄ these calls; the agent layer is untouched.
- Latency budget end-of-speech → first audio: p50 ≤ 2.5 s, p95 ≤ 4 s (STT 400–900 ms +
  first agent sentence 600–1500 ms + first TTS chunk 300–500 ms).
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

## Decisions
1. **Twilio Programmable Voice + Media Streams over `<Gather>`/`<Say>`** — Media Streams
   gives raw audio, keeping OpenAI STT/TTS (the stack directive) and the LlamaIndex
   agent in the loop; `<Gather>`/`<Say>` would replace both with Twilio's models.
2. **Adapter over rewrite** — the phone channel is a second implementation of the Phase 1
   session-bridge interface; agent, tools, memory, and scheduling are reused unchanged.
3. **STT = `gpt-4o-transcribe`, turn-based with server-side VAD** — better than
   `whisper-1` on error codes/model numbers; turn-based keeps the pipeline debuggable.
   OpenAI Realtime API still rejected unless the latency budget fails (tech-stack.md).
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

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; builds directly on the
  Phase 1 WS bridge and sentence-chunked TTS.
- Constraints: mission non-negotiables (safety interrupt and never-re-ask apply verbatim
  on the phone channel); no other telephony provider SDKs.
- Open questions (deferred): browser-mic STT loop for the web client — backlog, the
  phone channel makes it optional; answering-machine detection — backlog.
- Trial-account caveat: calls on a Twilio trial account play a spoken disclaimer before
  the `<Connect><Stream>` TwiML executes, adding latency ahead of the app's own
  greeting. This is expected trial behavior, not a defect — call it out explicitly
  rather than letting it silently read as a live-call checklist failure.
