# Twilio Telephony (Live Phone Channel) — Validation

## Automated
- [ ] Webhook signature validation: unsigned/mis-signed requests rejected; signed
      request returns the `<Connect><Stream>` TwiML.
- [ ] Codec round-trip: μ-law 8 kHz → PCM → μ-law byte-stable on fixtures.
- [ ] VAD endpointing unit tests against fixture audio (speech, silence, hangover).
- [ ] Bridge unit test: scripted `start`/`media`/`stop` sequence creates a
      `channel='phone'` session and produces outbound `media` frames.
- [ ] `make eval` green on phone-channel transcripts captured during the live-call
      checklist (same conversational metrics at the text level; audio-level evals stay
      in the backlog).
- [ ] `make lint` + `make test` clean.

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
6. Per-turn latency logs within budget (p50 ≤ 2.5 s to first audio).

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; live-call checklist passed.
- [ ] Constitution updates (mission scope, tech-stack models/secrets, roadmap) shipped
      with this feature.
- [ ] Deferred scope (MMS, outbound, transfer, full-duplex) recorded in the backlog.
- [ ] Roadmap Phase 5 ticked `[x]`.
