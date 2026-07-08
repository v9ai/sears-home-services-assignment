# Roadmap

Phased sequence; each phase names its feature triplet. A phase is ticked `[x]` only when
its `validation.md` Definition of Done holds.

**Parallel execution**: after the Phase 0b foundation commit, ALL feature triplets
(Phases 1–5) start in parallel per `COORDINATION.md` — the phase numbers below define
the **integration/merge order**, not the start order.

## Phase 0 — SDD constitution + spec set

- [x] `specs/_sdd/` (constitution + templates), `specs/constitution/` (four docs incl.
      `COORDINATION.md`), and the six feature triplets authored and merged.

## Phase 0b — Foundation commit (lead, ~30 min, unblocks all parallel agents)

- [ ] Scaffold per `COORDINATION.md` §1: `app/contracts.py`, full `pyproject.toml`,
      stubbed `Makefile`, Compose skeleton, alembic env, package skeletons, `web/`
      scaffold, tool auto-discovery registry, `tests/` + `evals/` skeletons.

## Phase 1 — Tier 1: voice diagnostic core (text + TTS)

- [ ] `specs/features/2026-07-08-voice-diagnostic-core/` — greeting, appliance
      identification, symptom collection, troubleshooting with safety interrupt,
      case-file memory, WS session channel, Next.js chat page with TTS playback.
      Includes the **base Docker Compose skeleton** (app + postgres + web) because the
      DB is a Phase 1 dependency.

## Phase 1b — Test & eval harness (cross-cutting)

- [ ] `specs/features/2026-07-08-testing-evals/` — pytest scaffolding, transcript
      runner, DeepEval harness (scenario matrix, pinned thresholds, failure canaries),
      CI skip-warn wiring. Develops in parallel on fixture transcripts; flips to the
      live agent at integration.

## Phase 2 — Tier 2: technician scheduling

- [ ] `specs/features/2026-07-08-technician-scheduling/` — schema + seed, zip/specialty
      matching, slot offering, verbal confirmation, atomic booking.

## Phase 3 — Tier 3: visual diagnosis

- [ ] `specs/features/2026-07-08-visual-diagnosis/` — email capture, tokenized upload
      link, GPT-4 Vision (`gpt-4o`) analysis merged into the case file, enhanced
      troubleshooting.

## Phase 4 — Deliverables hardening

- [ ] `specs/features/2026-07-08-deployment-deliverables/` — Compose polish
      (healthchecks, entrypoint migrate+seed), multi-stage Dockerfiles, **Cloudflare
      Containers deploy** of `web` + `app` (wrangler), complete README, 1–2 page
      `docs/technical-design.md`, final `.env.example`.

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
  outbound calls / SMS confirmations / transfer-to-human · full-duplex speech ·
  R2 for durable hosted upload storage · phone-channel audio-level evals
  (latency / word-error on μ-law audio) · load & perf testing.

## Non-goals (mirror of mission scope-out)

Payments · real PII compliance · multi-language · mobile apps · non-Twilio telephony
providers.
