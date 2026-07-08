# Twilio Telephony (Live Phone Channel) — Plan

Implement in dependency order; the media bridge (group 3) is the risky group — run it
alone and pause for review before going live.

## 1. Webhook + TwiML
- [ ] `POST /twilio/voice` returning `<Connect><Stream>` TwiML; `X-Twilio-Signature`
      validation; unit tests with recorded signed requests.

## 2. Codec + VAD
- [ ] μ-law 8 kHz ⇄ PCM resample/encode helpers; 20 ms framing.
- [ ] Server-side VAD endpointing (~300 ms hangover) over inbound frames; unit-tested
      against fixture audio.

## 3. Media Streams bridge                             ⏸ review after this group
- [ ] `/ws/twilio` endpoint: `start`/`media`/`stop` handling, session creation with
      `channel='phone'`, caller number capture.
- [ ] Wire to the shared session-bridge interface: buffered utterance → STT
      (`gpt-4o-transcribe`) → agent → sentence-chunked TTS → μ-law frames out.
- [ ] Barge-in: speech-during-playback sends `clear` and yields the turn.

## 4. Dev exposure + number
- [x] Provision the Twilio number: `+13186468479` ((318) 646-8479, Louisiana), SID
      `PN356e3d2a44afd34496997e66fb547da2`, via
      `twilio api:core:incoming-phone-numbers:create --phone-number=+13186468479`
      (`phone-numbers:buy:local` doesn't exist in `twilio-cli` 6.2.4).
- [ ] Compose `phone` profile: ngrok service, `PUBLIC_HOST` wiring.
- [ ] Twilio console: number's voice webhook → `{PUBLIC_HOST}/twilio/voice`; document
      the setup steps in the README.

## 5. Latency instrumentation
- [ ] Log end-of-speech → first-audio per turn; compare against the budget
      (p50 ≤ 2.5 s / p95 ≤ 4 s).

## 6. Gates
- [ ] `make lint` + `make test` clean (webhook, codec, VAD, bridge units).
- [ ] Manual live-call checklist (validation.md) passed end-to-end.
- [ ] Tick roadmap Phase 5 `[x]` in `specs/constitution/roadmap.md`.
