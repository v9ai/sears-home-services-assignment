# Roadmap

Phased sequence; each phase names its feature triplet. A phase is ticked `[x]` only when
its `validation.md` Definition of Done holds.

## Phase 0 — SDD constitution + spec set

- [x] `specs/_sdd/` (constitution + templates), `specs/constitution/` (this three-doc set),
      and the four feature triplets below authored and merged.

## Phase 1 — Tier 1: voice diagnostic core (text + TTS)

- [ ] `specs/features/2026-07-08-voice-diagnostic-core/` — greeting, appliance
      identification, symptom collection, troubleshooting with safety interrupt,
      case-file memory, WS session channel, static chat page with TTS playback.
      Includes the **base Docker Compose skeleton** (app + postgres) because the DB is a
      Phase 1 dependency.

## Phase 2 — Tier 2: technician scheduling

- [ ] `specs/features/2026-07-08-technician-scheduling/` — schema + seed, zip/specialty
      matching, slot offering, verbal confirmation, atomic booking.

## Phase 3 — Tier 3: visual diagnosis

- [ ] `specs/features/2026-07-08-visual-diagnosis/` — email capture, tokenized upload
      link, GPT-4o vision analysis merged into the case file, enhanced troubleshooting.

## Phase 4 — Deliverables hardening

- [ ] `specs/features/2026-07-08-deployment-deliverables/` — Compose polish (one-shot
      migrate+seed service, healthchecks), multi-stage Dockerfile, complete README,
      1–2 page `docs/technical-design.md`, final `.env.example`.

## Phase 5 — Twilio telephony: live phone channel

Where the assignment's **live phone number** deliverable lands. Provider fixed by user
directive (2026-07-08): **Twilio Programmable Voice + Media Streams**, adapting the same
session bridge; STT (`gpt-4o-transcribe`) enters here since the phone channel is
audio-only.

- [ ] `specs/features/2026-07-08-telephony-twilio/` — voice webhook + TwiML, Media
      Streams bridge with μ-law⇄PCM adapter, server-side VAD, barge-in via `clear`,
      `channel='phone'` sessions, ngrok Compose profile, live number wiring.

## Enhancement backlog

- Browser-mic STT loop for the web client (optional — the phone channel covers voice).
- RAG over manufacturer service manuals (LlamaIndex `VectorStoreIndex`) once the curated
  YAML knowledge outgrows itself.
- Reschedule/cancel flows · appointment reminder emails · MMS image ingestion ·
  outbound calls / SMS confirmations / transfer-to-human · full-duplex speech.

## Non-goals (mirror of mission scope-out)

Payments · real PII compliance · multi-language · mobile apps · non-Twilio telephony
providers.
