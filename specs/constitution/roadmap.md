# Roadmap

Phased sequence; each phase names its feature triplet. A phase is ticked `[x]` only when
its `validation.md` Definition of Done holds.

**Parallel execution**: after the Phase 0b foundation commit, ALL feature triplets
(Phases 1–5) start in parallel per `COORDINATION.md` — the phase numbers below define
the **integration/merge order**, not the start order.

## Integration status (2026-07-08, post-merge)

All six features are **merged to main** and integrated (COORDINATION §5 steps 1–3
complete; 4–5 partial): phone real-agent adapter + greeting-on-answer wired
(`app/phone/real_agent.py`), upload + phone routers mounted, live transcript driver
shipped (`make transcript` fixture mode green; `--live` available), 192 tests green,
`make lint` / `make test` / `make transcript` all green.

**Remaining manual items — each blocked on a credential or live endpoint, and each is
exactly what keeps its phase unticked below:**
1. `make eval` judge scoring — **RUN 2026-07-08 with a real key: 22/28, gate RED.**
   Harness plumbing is verified and all 4 canaries correctly failed their metrics. The
   remaining blockers are ordinary fixture scenarios: `core_{dryer,hvac,washer}_safety`
   blocks Phase 1; `scheduling_{happy_booking,no_tech_in_zip,slot_conflict}` blocks
   Phase 2 and the required PDF Tier 2 path. Visual/Tier 3 evals block only the optional
   visual-diagnosis claim. Fix path: enrich fixture transcripts, calibrate rubrics/
   thresholds, or run/live-accept the integrated agent with equivalent evidence.
   **UNBLOCKED 2026-07-08**: the judge moved to DeepSeek `deepseek-chat` per the
   Model-provider boundary directive (tech-stack.md) — the quota-exhausted OpenAI key
   no longer gates `make eval`; re-run pending. Phases 1 and 2 stay unticked until the
   gate re-runs green on the DeepSeek judge.
2. DeepSeek live turn — **RUN 2026-07-08 with a real `DEEPSEEK_API_KEY`: PASS.**
   One turn through the production `run_turn`/`get_llm()` invoked four tools
   (`identify_appliance` → `record_symptom` → `get_troubleshooting_steps` ×2), case
   file gained `washer` + the symptom, 14 sentences streamed — DeepSeek function
   calling proven end-to-end. Open residue (deepseek-agent-llm validation): latency
   sample was 4.07 s to first sentence (over budget, single sample; `LLM_PROVIDER=
   openai` is the recorded mitigation) and the openai-fallback smoke turn.
3. Docker-first PDF smoke re-run: fresh clone + Compose + seeded technician count +
   no-SKIP Tier 2 booking transcript — blocks Phase 4.
4. Cloudflare contract implementation + dry-run + hosted deploy smoke (`make deploy`,
   `CLOUDFLARE_API_TOKEN`) — blocks Phase 4; hosted-live claims wait for
   `instance_type`, `image_vars`, and `Container.envVars` to be implemented, plus real
   app `/healthz`, web load, and WSS chat turn.
5. Twilio console webhook → `{PUBLIC_HOST}/twilio/voice` + live-call checklist (number
   `+1 (318) 646-8479` provisioned) — blocks Phase 5.

## Phase 0 — SDD constitution + spec set

- [x] `specs/_sdd/` (constitution + templates), `specs/constitution/` (four docs incl.
      `COORDINATION.md`), and the six feature triplets authored and merged.

## Phase 0b — Foundation commit (lead, ~30 min, unblocks all parallel agents)

- [x] Scaffold per `COORDINATION.md` §1: `app/contracts.py`, full `pyproject.toml`,
      stubbed `Makefile`, Compose skeleton, alembic env, package skeletons, `web/`
      scaffold, tool auto-discovery registry, `tests/` + `evals/` skeletons.
      (Landed as commit `6d0dcda`.)

## Phase 1 — Tier 1: voice diagnostic core (text + TTS)

- [ ] `specs/features/2026-07-08-voice-diagnostic-core/` — greeting, appliance
      identification, symptom collection, troubleshooting with safety interrupt,
      case-file memory, WS session channel, Next.js chat page with TTS playback.
      Includes the **base Docker Compose skeleton** (app + postgres + web) because the
      DB is a Phase 1 dependency.
      **Status:** functionality verified (Team A — safety-interrupt, never-re-ask,
      tool-discovery, LLM swap; Team C — WS chat live end-to-end; DeepSeek live turn
      passed). Code is correct; **gated on** `make eval` RED (`core_*_safety`), itself
      blocked on a funded `OPENAI_API_KEY` (repo `.env` key is 429 quota-exhausted).

## Phase 1b — Test & eval harness (cross-cutting)

- [x] `specs/features/2026-07-08-testing-evals/` — pytest scaffolding, transcript
      runner, DeepEval harness (scenario matrix, pinned thresholds, failure canaries),
      CI skip-warn wiring. Develops in parallel on fixture transcripts; flips to the
      live agent at integration.

## Phase 2 — Tier 2: technician scheduling

- [ ] `specs/features/2026-07-08-technician-scheduling/` — schema + seed, zip/specialty
      matching, slot offering, verbal confirmation, atomic booking.
      **Status:** functionality verified (Team A — atomic booking, matching,
      seed/migrations against real Postgres). Code is correct; **gated on** `make eval`
      RED (`scheduling_*`), itself blocked on a funded `OPENAI_API_KEY`.

## Phase 3 — Tier 3: visual diagnosis

- [ ] `specs/features/2026-07-08-visual-diagnosis/` — email capture, tokenized upload
      link, GPT-4 Vision (`gpt-4o`) analysis merged into the case file, enhanced
      troubleshooting.
      **Status:** verified at merge time by the feature agent (not independently
      re-verified this round). **Gated on** `make eval` visual scenarios + a real
      GPT-4o Vision call — both blocked on a funded `OPENAI_API_KEY`.

## Phase 4 — Deliverables hardening

- [ ] `specs/features/2026-07-08-deployment-deliverables/` — Compose polish
      (healthchecks, entrypoint migrate+seed), multi-stage Dockerfiles, **Cloudflare
      Containers deploy** of `web` + `app` (wrangler), complete README, 1–2 page
      `docs/technical-design.md`, final `.env.example`.
      **Status:** Compose/README/design-doc hardening verified (self-contained
      `docker compose up` confirmed after the `DATABASE_URL_DIRECT` fix). **Gated on**
      a hosted Cloudflare deploy (Team D, pending) + a no-SKIP fresh-clone Tier-2
      booking smoke (itself gated on the red eval).

## Phase 5 — Twilio telephony: live phone channel

Where the assignment's **live phone number** deliverable lands. Provider fixed by user
directive (2026-07-08): **Twilio Programmable Voice + Media Streams**, adapting the same
session bridge; STT (`gpt-4o-transcribe`) enters here since the phone channel is
audio-only.

- [ ] `specs/features/2026-07-08-telephony-twilio/` — voice webhook + TwiML, Media
      Streams bridge with μ-law⇄PCM adapter, server-side VAD, barge-in via `clear`,
      `channel='phone'` sessions, ngrok Compose profile, live number wiring.
      **Status:** functionality verified (Team B — webhook, signature validation, media
      bridge, STT, greeting-on-answer, session persistence; audio-streaming bug fixed).
      Code is correct; **gated on** the live-call checklist — missing
      `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `PUBLIC_HOST`.

## Phase 6 — Appliance-library RAG via local Qdrant (optional, flag-gated)

Promoted from the backlog by user directive (2026-07-08); **feasibility spike-verified
same day** (embedded Qdrant + FastEmbed local embeddings; 24 symptom-tree docs ingested
in 1.5 s, 3 retrievals in 18 ms, correct safety-aware top hits). Augmentation-only:
deterministic YAML trees stay the primary path; `LIBRARY_RAG_ENABLED` default off.

- [ ] `specs/features/2026-07-08-appliance-library-qdrant/` — `make ingest`
      (YAML trees + `docs/library/` manuals), embedded Qdrant on the `qdrant_data`
      volume, `search_appliance_library` tool, eval extension + retrieval canary.

## Phase 7 — Call recording & in-app replay (no auth)

User directive (2026-07-08). Foundation already exists — Phase 1's per-turn session
persistence on both channels; this adds audio capture at synthesis/STT time, a
read-only no-auth calls API, and a `/calls` replay UI. Independent of Phases 4–6;
implementable immediately by a parallel agent.

- [ ] `specs/features/2026-07-08-call-recording-replay/` — recording hooks
      (`ts`/`audio_seq` transcript keys + audio files on the `recordings` volume),
      `GET /api/calls*` endpoints, `/calls` + `/calls/[id]` replay pages reusing
      `audioQueue.ts`; privacy note in README (open access by directive).

## Enhancement backlog

- Browser-mic STT loop for the web client (optional — the phone channel covers voice).
- Reschedule/cancel flows · appointment reminder emails · MMS image ingestion ·
  outbound calls / SMS confirmations / transfer-to-human · full-duplex speech ·
  phone-channel audio-level evals (latency / word-error on μ-law audio) ·
  load & perf testing.

Upload storage is a **Docker named volume by decision** (user directive 2026-07-08 —
object storage incl. Cloudflare R2 rejected); hosted-disk ephemerality on Cloudflare
Containers is an accepted, README-documented limitation, not a backlog item.

## Non-goals (mirror of mission scope-out)

Payments · real PII compliance · multi-language · mobile apps · non-Twilio telephony
providers.
