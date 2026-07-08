# Tech Stack

## Runtime

- **Python 3.12**, **FastAPI + uvicorn**, single app container.
- **WebSocket** session channel at `/ws/call`: JSON text messages in, transcript events
  and streamed TTS audio chunks out. The WS bridge is the durable abstraction — the
  Twilio Media Streams adapter (`/ws/twilio`, roadmap Phase 5) is a second implementation
  of the same session-bridge interface, so the Phase 1 transport layer adapts rather than
  being thrown away.
- **Telephony (Phase 5)**: Twilio Programmable Voice + Media Streams (bidirectional WS,
  base64 μ-law 8 kHz) behind a codec/resample adapter; `X-Twilio-Signature` validated on
  the voice webhook; ngrok Compose profile for dev exposure.

## Frontend

- **Next.js (App Router, TypeScript)** in `web/` — chat page (text input, live
  transcript, auto-playing TTS audio queue, case-file panel) and the Tier 3 upload page
  (`/upload/[token]`).
- Talks to the FastAPI backend over REST + WSS (`NEXT_PUBLIC_API_URL`,
  `NEXT_PUBLIC_WS_URL`); the FE is a **thin client** — no agent, model, or business
  logic in the browser; all OpenAI calls stay server-side.
- Local single-command launch: a `web` service in Compose runs the same app, so
  `docker compose up` remains self-sufficient without any cloud account.

## Hosting (Cloudflare Containers)

- Hosted deploys run on **Cloudflare Containers** (Workers-routed containers, deployed
  with `wrangler deploy`): the **same Dockerfiles** Compose uses build the `web` and
  `app` container images — no separate build path.
- Each service gets a Worker entry (`wrangler.toml` per service, or one Worker routing
  both); Workers terminate HTTP + **WebSockets**, which is what `/ws/call` and the
  Twilio Media Streams bridge (`/ws/twilio`, Phase 5) need — the hosted backend has a
  public WSS URL without ngrok.
- ngrok stays a **local-dev-only** convenience for Twilio webhooks against a laptop.
- Postgres is **not** containerized on Cloudflare — hosted deploys point `DATABASE_URL`
  at **Neon** (managed Postgres); locally the Compose `db` service remains. Use Neon's
  **pooled** connection string for the app (asyncpg through PgBouncer) and the
  **direct** connection string for Alembic migrations.

## Agent framework

- **LlamaIndex** (`llama_index.core.agent.workflow`): a single `FunctionAgent` run via
  `AgentWorkflow`, tools as plain async Python functions. Tool/function calling runs
  through LlamaIndex's `FunctionCallingLLM` interface — the provider is swappable at
  the single factory `app/agent/core.py:get_llm()` (DeepSeek by default, see Models).
- **Memory**: LlamaIndex `ChatMemoryBuffer` per session **plus** a structured pydantic
  **case file** persisted to Postgres and injected into the system prompt every turn —
  this is what makes mission non-negotiable 2 ("never re-ask") structural.

## Models

| Role   | Model                | Notes                                                        |
|--------|----------------------|--------------------------------------------------------------|
| LLM    | **DeepSeek `deepseek-chat`** | direct `api.deepseek.com` via `llama-index-llms-deepseek` (`DeepSeek`, a `FunctionCallingLLM`); `DEEPSEEK_MODEL` override; `LLM_PROVIDER=openai` falls back to `gpt-4o`; `deepseek-reasoner` rejected — no function calling. See `2026-07-08-deepseek-agent-llm/`. |
| TTS    | `gpt-4o-mini-tts`    | streamed, steerable "warm service agent" voice instructions   |
| Vision | **GPT-4 Vision** via `gpt-4o` | the assignment's "GPT-4 Vision" option — `gpt-4o` is its current API (the `gpt-4-vision-preview` endpoint is retired); chat-with-image, JSON-schema response (Tier 3) |
| STT    | `gpt-4o-transcribe`  | phone channel (Phase 5); `whisper-1` behind an env flag       |

## Database

- **PostgreSQL 18** — Compose service `db` locally (`postgres:18-alpine`); **Neon** for
  hosted deploys (same `DATABASE_URL` contract, no code difference). Neon project:
  `damp-shape-82273628` (`sears-home-services-assignment`, aws-us-east-1, db `neondb`,
  PG 18 — provisioned and connection-verified 2026-07-08).
- **SQLAlchemy 2.0 async** (asyncpg) + **Alembic** migrations. Explicit `select()`s only.
- Idempotent seed script (`make seed`): 8 technicians across ~6 zip codes covering all six
  appliance specialties, with a two-week rolling slot horizon.

## Make commands

| Command           | Does                                                            |
|-------------------|-----------------------------------------------------------------|
| `make up`         | `docker compose up --build` — the single-command launch          |
| `make dev`        | local uvicorn with reload against the Compose db                 |
| `make web-dev`    | `next dev` in `web/` against the local backend                   |
| `make migrate`    | `alembic upgrade head`                                           |
| `make seed`       | idempotent technician/slot seed                                  |
| `make test`       | pytest                                                           |
| `make lint`       | `ruff check` + `ruff format --check`                             |
| `make transcript` | scripted text-mode E2E conversation gate (hard pass/fail)        |
| `make eval`       | **DeepEval** conversational gate over the transcript scenarios   |
| `make deploy`     | `wrangler deploy` of `app` + `web` to Cloudflare Containers      |

## Evaluation (DeepEval)

Two-layer conversation gating, both hard pass/fail:

1. **`make transcript`** — deterministic structural assertions over scripted
   conversations (case-file contents, safety routing, booking row present).
2. **`make eval`** — **DeepEval** (pytest-integrated) conversational metrics judged by
   `gpt-4o` — deliberately a *different provider* than the DeepSeek agent under test,
   so the system never grades itself — over the same scenario transcripts: **Knowledge Retention** (the
   never-re-ask non-negotiable, measured), **Role Adherence** (warm service-agent
   persona), **Conversation Completeness** (caller's issue resolved or escalated), and
   custom **G-Eval rubrics per feature** — safety interrupt (Tier 1), booking
   confirmation read-back (Tier 2), photo-findings incorporation (Tier 3).
   Scenario matrix, metric config, and pinned thresholds live in `evals/` and are
   specified in `specs/features/2026-07-08-testing-evals/`; a failing metric blocks the
   feature like any other gate. Judge calls use `OPENAI_API_KEY`; `make eval` is
   skipped-with-warning when the key is absent (offline CI), never silently green.

## Forbidden patterns

- **No LangChain / LangGraph** — LlamaIndex is the sole agent framework.
- **No OpenAI Realtime API** — it bypasses LlamaIndex tool orchestration and hides the
  STT→agent→TTS seams the design doc must demonstrate; revisit only if the Phase 5
  latency budget fails.
- **No vector DB / embeddings for diagnostic knowledge** — deterministic keyed YAML lookup
  (see the voice-diagnostic-core spec, Decision 3). RAG-over-manuals is a recorded roadmap
  enhancement, not a default.
- **No raw SQL string interpolation** — parameterized SQLAlchemy only.
- **No hand-applied schema changes** — Alembic only.
- **Telephony = Twilio only** — no other provider SDKs; Twilio code lands only under its
  feature triplet (Phase 5).
- **No agent/LLM logic in the frontend** — the Next.js app renders and relays; every
  OpenAI/LlamaIndex call happens in the FastAPI backend.

## Secrets (`.env.example` is the contract)

Backend: `DEEPSEEK_API_KEY` (agent LLM) + optional `DEEPSEEK_MODEL` / `LLM_PROVIDER`,
`OPENAI_API_KEY` (TTS, STT, vision, DeepEval judge), `DATABASE_URL` (pooled on Neon),
`DATABASE_URL_DIRECT`
(direct string — Alembic migrations + seed), `APP_BASE_URL` (the FE base URL used in
emailed links), `CF_EMAIL_API_TOKEN` + `EMAIL_FROM` (Tier 3, Cloudflare Email Service),
`UPLOAD_TOKEN_SECRET` (reserved),
`EMAIL_BACKEND` (`cloudflare` | `smtp` | `console`), `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `PUBLIC_HOST`, `NGROK_AUTHTOKEN` (Phase 5).
Frontend (`web/.env.example`; wrangler vars on Cloudflare): `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_WS_URL`. Cloudflare deploys authenticate via `wrangler login` /
`CLOUDFLARE_API_TOKEN`.
