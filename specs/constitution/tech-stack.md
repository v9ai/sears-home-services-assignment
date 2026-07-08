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
- Interim client: **one static HTML+JS page** served by FastAPI at `/` — text input, live
  transcript panel, auto-playing TTS audio. No frontend build toolchain.

## Agent framework

- **LlamaIndex** (`llama_index.core.agent.workflow`): a single `FunctionAgent` run via
  `AgentWorkflow`, tools as plain async Python functions.
- **Memory**: LlamaIndex `ChatMemoryBuffer` per session **plus** a structured pydantic
  **case file** persisted to Postgres and injected into the system prompt every turn —
  this is what makes mission non-negotiable 2 ("never re-ask") structural.

## Models (all OpenAI)

| Role   | Model                | Notes                                                        |
|--------|----------------------|--------------------------------------------------------------|
| LLM    | `gpt-4o`             | function calling + latency; `OPENAI_LLM_MODEL` env fallback   |
| TTS    | `gpt-4o-mini-tts`    | streamed, steerable "warm service agent" voice instructions   |
| Vision | `gpt-4o`             | chat-with-image, JSON-schema response format (Tier 3)         |
| STT    | `gpt-4o-transcribe`  | phone channel (Phase 5); `whisper-1` behind an env flag       |

## Database

- **PostgreSQL 16** (Compose service `db`).
- **SQLAlchemy 2.0 async** (asyncpg) + **Alembic** migrations. Explicit `select()`s only.
- Idempotent seed script (`make seed`): 8 technicians across ~6 zip codes covering all six
  appliance specialties, with a two-week rolling slot horizon.

## Make commands

| Command           | Does                                                            |
|-------------------|-----------------------------------------------------------------|
| `make up`         | `docker compose up --build` — the single-command launch          |
| `make dev`        | local uvicorn with reload against the Compose db                 |
| `make migrate`    | `alembic upgrade head`                                           |
| `make seed`       | idempotent technician/slot seed                                  |
| `make test`       | pytest                                                           |
| `make lint`       | `ruff check` + `ruff format --check`                             |
| `make transcript` | scripted text-mode E2E conversation gate (hard pass/fail)        |

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
- **No frontend build toolchain** (React/Next/bundlers) for the web client.

## Secrets (`.env.example` is the contract)

`OPENAI_API_KEY`, `DATABASE_URL`, `APP_BASE_URL`, `RESEND_API_KEY` (Tier 3),
`UPLOAD_TOKEN_SECRET` (reserved), `EMAIL_BACKEND` (`resend` | `smtp` | `console`),
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `PUBLIC_HOST`,
`NGROK_AUTHTOKEN` (Phase 5).
