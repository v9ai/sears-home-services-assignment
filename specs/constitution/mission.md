# Mission

## Vision

An inbound-call voice AI agent for **Sears Home Services**: a homeowner calls because an
appliance is misbehaving, and the agent greets them, identifies the appliance
(washer, dryer, refrigerator, dishwasher, oven, HVAC), collects symptoms (what is
happening, when it started, error codes, unusual sounds), walks them through safe
troubleshooting steps, and — when DIY won't cut it — books a qualified technician in
their zip code. Optionally, the agent emails the caller a unique link to upload a photo
of the appliance, and uses computer vision to sharpen the diagnosis.

This is the Sears Home Services AI Engineer take-home assignment, built spec-first.
Verbatim source: `docs/assignment/SHS_AI_Engineer_Take-Home_v8.pdf`.

## What the reviewers value (assignment §6–7, binding on scope calls)

- **Working software over perfect software** — ship functional tiers before polishing.
- **Pragmatic engineering** — existing tools/services over reinvention.
- **Clear communication** — the design doc reads like an explanation to a colleague.
- **Caller experience** — latency, natural flow, helpful responses (the latency budgets
  in the feature specs are this value, quantified).
- **Cost** — select free tiers where possible (Neon free plan, Twilio trial, Cloudflare
  free tier); agent tokens run on DeepSeek's cheap `deepseek-chat`, OpenAI spend is
  narrowed to voice/vision/judge, and the deterministic knowledge base keeps all LLM
  usage minimal.
- Timeline context: 7 days; ~3–4 h focused effort estimated for Tier 1 + Tier 2 — the
  roadmap's phase cut mirrors that weighting.

## Audience

- **Primary**: Sears take-home reviewers — the repo is a signal of production judgment:
  architecture, schema design, tradeoff reasoning, and honest sequencing of deferred work.
- **Secondary**: the simulated caller exercising the demo.

Single-tenant demo. No auth product surface, no multi-tenancy, no marketing.

## Scope

**In scope:**
- Assignment Tiers 1–3: diagnostic conversation, technician scheduling, visual diagnosis.
- Dev/demo channel first: **text chat + OpenAI TTS playback** — the caller types, the
  agent replies with text and spoken audio (roadmap Phase 1). It stays as the permanent
  debug harness. The web client is a **Next.js app**; hosted deploys (frontend and
  backend) run on **Cloudflare Containers**, and a Compose `web` service keeps the
  local single-command launch self-sufficient.
- Live phone channel: **Twilio Programmable Voice + Media Streams**, handled by a
  **Pipecat** voice pipeline (Deepgram STT → LLM → TTS; feature
  `2026-07-09-pipecat-voice-port`, which superseded the hand-rolled Phase 5 media bridge)
  that reuses the same tools/prompts/guardrails/knowledge as the web channel — this
  delivers the assignment's live phone number.
- PostgreSQL persistence for sessions, technicians, scheduling, and uploads.
- **Call recording with a dedicated in-app recordings page** (`/recordings`, nav-linked,
  lists all calls on both channels) + full replay, open to all users with **no auth**
  (user directive 2026-07-08) — privacy tradeoff recorded in
  `2026-07-08-call-recording-replay/` Decision 2 and README known limitations.
- Single-command launch via Docker Compose.

**Explicitly out of scope:**
- Browser-mic STT for the web client — backlog; the phone channel makes it optional.
- Non-Twilio **telephony/PSTN** providers (Vonage/Plivo/Telnyx). The phone channel's
  *media* services — Deepgram STT, Silero VAD, optional Cartesia TTS via Pipecat — are in
  scope; Twilio stays the sole PSTN carrier.
- Payments, real customer PII handling/compliance, multi-language support, mobile apps.
- RAG over full appliance service manuals — recorded as a future enhancement; the demo
  uses deterministic curated knowledge (see `tech-stack.md`).

## Non-negotiables

No feature may violate these:

1. **Safety interrupt.** Any mention of gas smell, sparking, burning smell, smoke, or
   water near electrics halts troubleshooting immediately: advise shutoff and professional
   help, offer to schedule a technician. No flow may route around this.
2. **Never re-ask.** Once a fact (appliance, symptom, zip, name, email, availability) is
   captured in the session case file, no prompt or flow may ask for it again. Enforced
   structurally — the case file is injected into the agent's context every turn — not by
   prompt hope.
3. **Single-command launch.** `docker compose up` from a fresh clone plus a populated
   `.env` must always produce a working system: fresh DB → migrate → seed → serve.
4. **Booking integrity.** An appointment exists only over an atomically claimed slot, and
   only after the agent has read back technician + date + time and received an explicit yes.
5. **Secrets via env only.** `.env.example` is the contract; no keys in git.
6. **Spec-first.** Code lands only under a `specs/features/` triplet. Constitution-revising
   changes update these documents in the same commit.
