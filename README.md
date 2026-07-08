# Sears Home Services — Voice AI Diagnostic Agent

Take-home technical project (AI Engineer): an inbound-call voice AI agent that helps
customers diagnose home-appliance issues, walks them through safe troubleshooting, books
a technician when DIY won't cut it, and optionally sharpens the diagnosis with a photo
the caller uploads via an emailed link.

**Current state: spec phase — no application code yet.** This repo is built spec-first;
the documents below are the source of truth the implementation will be generated from.

## Stack (constitutional)

LlamaIndex (`FunctionAgent` + `AgentWorkflow`) · DeepSeek `deepseek-chat` agent LLM
(direct, LlamaIndex function calling; `gpt-4o` env fallback) · PostgreSQL 18
(SQLAlchemy 2 async + Alembic) · OpenAI (`gpt-4o-mini-tts` TTS, `gpt-4o-transcribe` STT
on the phone channel, GPT-4 Vision via `gpt-4o`, DeepEval judge) · FastAPI + WebSocket ·
Next.js frontend · Cloudflare Containers (hosted deploys) · Twilio Programmable Voice +
Media Streams (live phone channel) · Docker Compose.

## How to read this repo

1. `specs/constitution/mission.md` — why, scope, and the non-negotiables.
2. `specs/constitution/tech-stack.md` — runtime, models, commands, forbidden patterns.
3. `specs/constitution/roadmap.md` — phased sequence, backlog, non-goals.
4. `specs/constitution/COORDINATION.md` — how all features run **in parallel** by
   independent agents (ownership map, frozen contracts, integration order).
5. The feature triplets (below), each `requirements.md` → `plan.md` → `validation.md`.

The method itself is documented in `specs/_sdd/constitution.md`. The verbatim
assignment is vendored at `docs/assignment/SHS_AI_Engineer_Take-Home_v8.pdf`.

## Feature map

| Assignment tier | Feature spec | Status |
|---|---|---|
| Tier 1 — diagnostic conversation (text + TTS harness) | `specs/features/2026-07-08-voice-diagnostic-core/` | Specified |
| Tests & evals — pytest + DeepEval gates | `specs/features/2026-07-08-testing-evals/` | Specified |
| Tier 2 — technician scheduling | `specs/features/2026-07-08-technician-scheduling/` | Specified |
| Tier 3 — visual diagnosis | `specs/features/2026-07-08-visual-diagnosis/` | Specified |
| Deliverables — Compose, README, design doc | `specs/features/2026-07-08-deployment-deliverables/` | Specified |
| Live phone number — Twilio channel | `specs/features/2026-07-08-telephony-twilio/` | Specified — number provisioned: **+1 (318) 646-8479** |

All six features are designed to start **in parallel** (independent Claude Code agents,
one per triplet) after a ~30-minute foundation commit — see `COORDINATION.md`.

Run instructions land with the `deployment-deliverables` feature (`make up` /
`docker compose up` is the contract — see mission non-negotiable 3).
