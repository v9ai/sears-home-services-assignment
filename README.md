# Sears Home Services — Voice AI Diagnostic Agent

An inbound-call voice AI agent for Sears Home Services: a homeowner calls (or chats)
because an appliance is misbehaving, and the agent identifies the appliance, collects
symptoms, walks them through safe troubleshooting, and — when DIY won't cut it — books a
qualified technician in their zip code. Optionally, it emails the caller a link to
upload a photo and uses GPT-4 Vision to sharpen the diagnosis.

Take-home technical project (AI Engineer). Verbatim source:
`docs/assignment/SHS_AI_Engineer_Take-Home_v8.pdf`. Built **spec-first** — every line of
code traces back to a `specs/features/<tier>/requirements.md` → `plan.md` →
`validation.md` triplet; see "How to read this repo" below.

## Quickstart

```bash
git clone <this-repo-url> && cd sears-home-services-assignment
cp .env.example .env            # fill in OPENAI_API_KEY at minimum (see Configuration)
make up                         # == docker compose up --build
open http://localhost:3000      # chat page; backend on :8000, /healthz should read 200
```

That's it — `make up` brings up Postgres, runs migrations + the idempotent seed, and
serves the FastAPI backend (`:8000`) and the Next.js chat frontend (`:3000`). No other
account or service is required for the local demo channel (text chat + TTS playback).
The live Twilio phone number is a separate, optional channel — see
[Configuration](#configuration).

Tear down: `docker compose down` (add `-v` to also drop the local Postgres volume).

## Architecture

```
                         ┌─────────────────────────────┐
   caller (browser) ───▶ │   web  (Next.js, :3000)     │
                         │   chat page + upload page    │
                         └──────────────┬───────────────┘
                                        │ REST + WSS (/ws/call)
                                        ▼
   caller (phone) ─▶ Twilio ─▶ /twilio/voice, /ws/twilio (Phase 5)
                                        │
                         ┌──────────────▼───────────────┐
                         │   app  (FastAPI, :8000)       │
                         │  ┌─────────────────────────┐  │
                         │  │ SessionBridge (WS/phone)│  │
                         │  └───────────┬─────────────┘  │
                         │  ┌───────────▼─────────────┐  │
                         │  │ LlamaIndex FunctionAgent │  │      DeepSeek: deepseek-chat (LLM)
                         │  │  + case file (never      │──────▶ OpenAI:
                         │  │    re-ask memory)         │  │     gpt-4o-mini-tts (TTS)
                         │  └───────────┬─────────────┘  │      gpt-4o-transcribe (STT)
                         │  ┌───────────▼─────────────┐  │      gpt-4o (Vision)
                         │  │ Tools (auto-discovered)  │  │
                         │  │  core · scheduling ·     │  │
                         │  │  visual · (registry.py)  │  │
                         │  └───────────┬─────────────┘  │
                         │  ┌───────────▼─────────────┐  │
                         │  │ knowledge/*.yaml         │  │  deterministic decision
                         │  │ (deterministic lookup)   │  │  trees, no RAG/vector DB
                         │  └──────────────────────────┘  │
                         └──────────────┬───────────────┘
                                        │ SQLAlchemy async (asyncpg)
                                        ▼
                         ┌───────────────────────────────┐
                         │ PostgreSQL 18                 │
                         │ sessions · customers ·         │
                         │ technicians · availability ·   │
                         │ appointments · image_uploads   │
                         └───────────────────────────────┘
```

- Local: Docker Compose runs `db` + `app` + `web` (`docker-compose.yml`); an optional
  `phone` profile adds `ngrok` to expose the backend to Twilio webhooks during dev.
- Hosted: `app` and `web` deploy to **Cloudflare Containers** via `wrangler deploy`
  (`wrangler.app.toml`, `wrangler.web.toml`), building the **same Dockerfiles** Compose
  uses — no separate build path. Postgres is not containerized on Cloudflare; hosted
  deploys point at **Neon** (`DATABASE_URL` pooled / `DATABASE_URL_DIRECT` direct).
- The web WS bridge (`/ws/call`) and the Twilio Media Streams bridge (`/ws/twilio`,
  Phase 5) are two implementations of the same `SessionBridge` protocol
  (`app/contracts.py`) — the agent layer is transport-agnostic.

Full rationale, schema ERD, latency budgets, and tradeoffs: `docs/technical-design.md`.

## Feature tour (assignment tiers)

| Tier | What it does | Spec | Status |
|---|---|---|---|
| 1 — Diagnostic conversation | Greets caller, identifies one of six appliances (washer, dryer, refrigerator, dishwasher, oven, HVAC), collects symptoms, gives troubleshooting steps from a curated knowledge base, halts immediately on any safety signal (gas/sparking/smoke/water-near-electrics) | [`2026-07-08-voice-diagnostic-core`](specs/features/2026-07-08-voice-diagnostic-core/) | See `specs/constitution/roadmap.md` for current phase status |
| 2 — Technician scheduling | Matches technicians by zip + specialty, offers up to 3 slots, reads back name/date/time, books atomically only on explicit "yes" | [`2026-07-08-technician-scheduling`](specs/features/2026-07-08-technician-scheduling/) | See roadmap |
| 3 — Visual diagnosis | Captures email, sends a tokenized upload link, runs GPT-4 Vision on the photo, merges findings into the case file | [`2026-07-08-visual-diagnosis`](specs/features/2026-07-08-visual-diagnosis/) | See roadmap |
| Live phone number | Twilio Programmable Voice + Media Streams reusing the same agent/session bridge | [`2026-07-08-telephony-twilio`](specs/features/2026-07-08-telephony-twilio/) | Number provisioned: **+1 (318) 646-8479** — webhook wiring lands with this phase, see [Known limitations](#known-limitations) |
| Tests & evals | pytest structural gates + DeepEval conversational metrics over scripted scenarios | [`2026-07-08-testing-evals`](specs/features/2026-07-08-testing-evals/) | See roadmap |
| Deployment & deliverables (this doc) | Docker/Compose hardening, Cloudflare Containers deploy, README, design doc | [`2026-07-08-deployment-deliverables`](specs/features/2026-07-08-deployment-deliverables/) | Container + Compose hardening and Cloudflare deploy config (`Dockerfile`, `wrangler.app/web.toml`) done and **dry-run** verified; a hosted-live deploy has not been performed (see that feature's `plan.md`) |

The six feature triplets above were built **in parallel** by independent agents against
a shared foundation commit — see `specs/constitution/COORDINATION.md` for the ownership
map, frozen contracts, and integration order. `specs/constitution/roadmap.md` is the
single source of truth for what's merged vs. still landing at any given moment; this
README describes the designed system end-to-end and does not restate that status inline
per row, to avoid going stale.

## How to read this repo

This is a spec-driven repo: every feature is authored as a `requirements.md` →
`plan.md` → `validation.md` triplet **before** any code lands, per
`specs/_sdd/constitution.md`. Read in this order:

1. `specs/constitution/mission.md` — vision, scope, non-negotiables.
2. `specs/constitution/tech-stack.md` — runtime, models, Make commands, forbidden
   patterns, secrets contract.
3. `specs/constitution/roadmap.md` — phased sequence and current status per phase.
4. `specs/constitution/COORDINATION.md` — how six independent agents built this in
   parallel (ownership map, frozen contracts, stub seams, integration order).
5. Each feature triplet under `specs/features/<phase>/` — the actual design decisions.
6. `docs/technical-design.md` — the reviewer-facing 1–2 page distillation of all of the
   above; `docs/demo-script.md` — a 5-minute guided walkthrough; `docs/SUBMISSION.md` —
   the assignment's submission format (repo link, phone number, credentials,
   availability).

## Configuration

Copy `.env.example` to `.env` and fill in secrets — `.env.example` is the frozen
contract (mission non-negotiable 5: secrets via env only, nothing in git).

| Variable | Required for | Notes |
|---|---|---|
| `DEEPSEEK_API_KEY` | Agent LLM (`deepseek-chat`, LlamaIndex function calling) | `LLM_PROVIDER=openai` falls back to `gpt-4o` |
| `OPENAI_API_KEY` | TTS / STT / Vision / DeepEval judge | All model calls are server-side only (`tech-stack.md`) |
| `DATABASE_URL` | App runtime | Local Compose default works out of the box; hosted deploys use Neon's **pooled** string |
| `DATABASE_URL_DIRECT` | Migrations + seed | Local Compose default works out of the box; hosted deploys use Neon's **direct** string |
| `APP_BASE_URL` | Tier 3 emailed upload links | The frontend's public base URL (`localhost:3000` locally) |
| `EMAIL_BACKEND` | Tier 3 | `console` (default, prints to logs — no account needed) \| `cloudflare` \| `smtp` |
| `CF_EMAIL_API_TOKEN`, `EMAIL_FROM` | Tier 3, if `EMAIL_BACKEND=cloudflare` | Cloudflare Email Service |
| `UPLOAD_TOKEN_SECRET` | Reserved | Unused while upload tokens are DB-backed random tokens |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Phone channel only | Not needed for the text-chat demo |
| `PUBLIC_HOST`, `NGROK_AUTHTOKEN` | Phone channel, local dev only | `docker compose --profile phone up` starts an ngrok tunnel |
| `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` | Frontend | Inlined into the client bundle **at build time** — rebuild (`make up` / `make deploy`) after changing these, a running container won't pick up a runtime-only change |
| `RECORDINGS_DIR` | Call recording & replay | Default `data/recordings`; Docker named volume (`recordings`) mounts here |
| `REPLAY_TTS_FALLBACK` | Call recording & replay | Default off; when on, `/api/recordings/{id}/audio/{seq}` re-synthesizes turns without stored audio on demand instead of 404ing |

Cloudflare hosted deploys additionally need `wrangler login` (or `CLOUDFLARE_API_TOKEN`)
and per-service secrets set via `wrangler secret put <NAME> --config wrangler.app.toml`
— see the comments in `wrangler.app.toml` / `wrangler.web.toml`.

## Make commands

| Command | Does |
|---|---|
| `make up` | `docker compose up --build` — the single-command local launch |
| `make dev` | local uvicorn with reload against the Compose `db` |
| `make web-dev` | `next dev` in `web/` against the local backend |
| `make migrate` | `alembic upgrade head` |
| `make seed` | idempotent technician/slot seed |
| `make test` | pytest |
| `make lint` | `ruff check` + `ruff format --check` |
| `make transcript` | scripted text-mode E2E conversation gate |
| `make eval` | DeepEval conversational gate over the transcript scenarios |
| `make latency` | stage + end-to-end latency bench, writes `data/latency/{ts}.json` |
| `make deploy` | `wrangler deploy` of `app` + `web` to Cloudflare Containers |

Also: `./scripts/fresh_clone_smoke.sh` runs the fresh-clone rehearsal this feature's
gate requires (clone → env → compose up → healthchecks → `/healthz` → seeded-technician
check → booking round-trip; the last two skip with a warning until their owning
features land, see that script's header).

## Known limitations

- **Live phone number webhook wiring** — the Twilio number (**+1 (318) 646-8479**) is
  provisioned but still points at Twilio's demo webhook; rewiring it to
  `{PUBLIC_HOST}/twilio/voice` lands with `2026-07-08-telephony-twilio`.
- **No browser-mic speech-to-text** — the web client is text-in / audio-out (TTS
  playback); voice input on the web channel is backlog since the phone channel covers
  live voice.
- **No RAG over manufacturer manuals** — diagnostic knowledge is a deterministic, curated
  YAML lookup (six appliances × common issues), by design (`tech-stack.md` forbidden
  patterns) — not a stopgap, a scoping decision for a small, auditable knowledge base.
- **Ephemeral upload/recording storage on hosted (Cloudflare) deploys** — container disk
  isn't durable; an accepted, documented limitation for the demo. Object storage
  (including Cloudflare R2) was explicitly rejected (2026-07-08 directive) in favor of
  Docker named volumes (`uploads`, `recordings`), which persist under local Compose.
- **Call recording & replay has no auth, by explicit directive** — the `/recordings`
  page and its API expose every call's transcript and audio (names, zips, emails
  callers provide) to anyone who can reach the app, with no access control. Acceptable
  for this take-home (mission non-goal: real PII compliance); a production version
  would need auth + a retention policy before recording real customer calls.
- **No CI/CD pipeline** — out of take-home scope; deploys are direct `wrangler`
  invocations documented above.
- **No reschedule/cancel flows, no geo-radius technician matching, no multi-language
  support** — see `specs/constitution/roadmap.md` → Enhancement backlog / Non-goals for
  the complete deferred-scope list and the reasoning behind each cut.

## License

Take-home assignment submission — not licensed for reuse.
