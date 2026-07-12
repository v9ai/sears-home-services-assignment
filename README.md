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
curl http://localhost:8000/healthz   # should read {"status":"ok"}
```

That's it — `make up` brings up Postgres, runs migrations + the idempotent seed, and
serves the FastAPI backend (`:8000`). There is no frontend: the system is voice-first
(the live Twilio phone number is the caller-facing surface), and the backend itself
serves the one page the assignment needs — the Tier-3 photo-upload page at
`/upload/{token}`, reached via the emailed link. See [Configuration](#configuration).

`OPENAI_API_KEY` alone covers the local text/eval demo (`/healthz`, the upload page,
transcript replay). A **live phone call** with the default providers
(`STT_PROVIDER=deepgram`, `TTS_PROVIDER=cartesia`) additionally needs
`DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, and `TWILIO_AUTH_TOKEN` —
or set `STT_PROVIDER=openai` / `TTS_PROVIDER=openai` to stay one-key.

The `.env` file itself is optional: a literal `docker compose up --build` on a clone
with no `.env` still boots the full stack (DB, migrations, seed, `/healthz`, upload
page) — the agent surfaces just stay disabled until an LLM key exists.

For a **bookable demo**, use a seeded zip — Chicago `60601`/`60614`/`60642`, Dallas
`75201`/`75204`/`75225`; e.g. dishwasher @ 60601 (Marcus Bell) or oven @ 60614
(Priya Nair). The full zip × appliance cell table is in `docs/demo-script.md` §2;
any other zip demonstrates the graceful no-coverage reply instead.

Tear down: `docker compose down` (add `-v` to also drop the local Postgres volume).

## Architecture

```
   caller (browser, Tier-3 photo) ───▶ GET /upload/{token}  (served by the backend)
                                        │ REST (/api/upload)
                                        ▼
   caller (phone) ─▶ Twilio ─▶ /twilio/voice, /ws/twilio (Phase 5)
                                        │
                         ┌──────────────▼───────────────┐
                         │   app  (FastAPI, :8000)       │
                         │  ┌─────────────────────────┐  │
                         │  │ SessionBridge (WS/phone)│  │
                         │  └───────────┬─────────────┘  │
                         │  ┌───────────▼─────────────┐  │
                         │  │ LlamaIndex FunctionAgent │  │      OpenAI: gpt-4.1-mini (web LLM),
                         │  │  + case file (never      │──────▶  gpt-4.1-mini (phone LLM) · gpt-4o (Vision),
                         │  │    re-ask memory)         │  │      gpt-4o-mini-tts (web TTS)
                         │  └───────────┬─────────────┘  │      Cartesia: sonic-3.5 (phone TTS)
                         │  ┌───────────▼─────────────┐  │      Deepgram: streaming (phone STT)
                         │  │ Tools (auto-discovered)  │  │      DeepSeek: deepseek-chat (swap)
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

- Local: Docker Compose runs `db` + `app` (`docker-compose.yml`); an optional
  `phone` profile adds `ngrok` to expose the backend to Twilio webhooks during dev
  (a `cloudflared` quick tunnel is the equivalent current path, used in
  `docs/local-twilio-run.md`).
- Hosted: `app` deploys to **Cloudflare Containers** via `wrangler deploy`
  (`wrangler.app.toml`), building the **same Dockerfile** Compose uses — no separate
  build path. Postgres is not containerized on Cloudflare; hosted deploys point at
  **Neon** (`DATABASE_URL` pooled / `DATABASE_URL_DIRECT` direct).
- The text WS bridge (`/ws/call`, `app/ws/routes.py`) runs the LlamaIndex `FunctionAgent`
  directly over the `SessionBridge` protocol (`app/contracts.py`) — kept as the
  hermetic test/eval surface for the agent loop (no browser client ships with it).
- The **phone channel** (`/twilio/voice` + `/ws/twilio`) is a **Pipecat** pipeline
  (`app/voice`): Twilio Media Streams → Deepgram STT → OpenAI LLM → Cartesia TTS, with Silero
  VAD and barge-in. It reuses the **same** LlamaIndex tools, prompts, guardrails, and
  knowledge base — each LlamaIndex tool is re-exposed as a Pipecat function-calling tool.
  See [`app/voice/README.md`](app/voice/README.md) for the full inventory→mapping and how
  to run/tunnel/place a test call.

Full rationale, schema ERD, latency budgets, and tradeoffs: `docs/technical-design.md`.

## Feature tour (assignment tiers)

| Tier | What it does | Spec | Status |
|---|---|---|---|
| 1 — Diagnostic conversation | Greets caller, identifies one of six appliances (washer, dryer, refrigerator, dishwasher, oven, HVAC), collects symptoms, gives troubleshooting steps from a curated knowledge base, halts immediately on any safety signal (gas/sparking/smoke/water-near-electrics) | [`2026-07-08-voice-diagnostic-core`](specs/features/2026-07-08-voice-diagnostic-core/) | See `specs/constitution/roadmap.md` for current phase status |
| 2 — Technician scheduling | Matches technicians by zip + specialty, offers up to 3 slots, reads back name/date/time, books atomically only on explicit "yes" | [`2026-07-08-technician-scheduling`](specs/features/2026-07-08-technician-scheduling/) | See roadmap |
| 3 — Visual diagnosis | Captures email, sends a tokenized upload link, runs GPT-4 Vision on the photo, merges findings into the case file | [`2026-07-08-visual-diagnosis`](specs/features/2026-07-08-visual-diagnosis/) | See roadmap |
| Live phone number | Twilio Programmable Voice + Media Streams reusing the same agent/session bridge | [`2026-07-08-telephony-twilio`](specs/features/2026-07-08-telephony-twilio/) | Number provisioned, wired, and always available: **+1 (318) 646-8479** (hosted Worker webhook; see [Known limitations](#known-limitations)) |
| Tests & evals | pytest structural gates + DeepEval conversational metrics over scripted scenarios | [`2026-07-08-testing-evals`](specs/features/2026-07-08-testing-evals/) | See roadmap |
| Deployment & deliverables (this doc) | Docker/Compose hardening, Cloudflare Containers deploy, README, design doc | [`2026-07-08-deployment-deliverables`](specs/features/2026-07-08-deployment-deliverables/) | Container + Compose hardening done; **hosted Cloudflare deploy live** (2026-07-08: `make deploy` shipped both Workers, `/healthz` 200, scripted WSS chat turn passed — roadmap item 4) |

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
| `APP_BASE_URL` | Tier 3 emailed upload links | The backend's public base URL (`localhost:8000` locally) — the backend serves the upload page at `/upload/{token}` |
| `EMAIL_BACKEND` | Tier 3 | `console` (default, prints to logs — no account needed) \| `cloudflare` \| `smtp` |
| `CF_ACCOUNT_ID`, `CF_EMAIL_API_TOKEN`, `EMAIL_FROM` | Tier 3, if `EMAIL_BACKEND=cloudflare` | Cloudflare Email Service (account id + API token + verified sender) |
| `UPLOAD_TOKEN_SECRET` | Reserved | Unused while upload tokens are DB-backed random tokens |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Phone channel only | Not needed for the text-chat demo |
| `PUBLIC_HOST`, `NGROK_AUTHTOKEN` | Phone channel, local dev only | `docker compose --profile phone up` starts an ngrok tunnel |
| `RECORDINGS_DIR` | Call recording & replay | Default `data/recordings`; Docker named volume (`recordings`) mounts here |
| `REPLAY_TTS_FALLBACK` | Call recording & replay | Default off; when on, `/api/recordings/{id}/audio/{seq}` re-synthesizes turns without stored audio on demand instead of 404ing |

Cloudflare hosted deploys additionally need `wrangler login` (or `CLOUDFLARE_API_TOKEN`)
and per-service secrets set via `wrangler secret put <NAME> --config wrangler.app.toml`
— see the comments in `wrangler.app.toml`.

## Make commands

| Command | Does |
|---|---|
| `make up` | `docker compose up --build` — the single-command local launch |
| `make dev` | local uvicorn with reload against the Compose `db` |
| `make migrate` | `alembic upgrade heads` |
| `make seed` | idempotent technician/slot seed |
| `make test` | **stutter hard gate + `pytest tests`** — the primary unit/integration suite |
| `make stutter` | hermetic phone-audio stutter bench (keyless HARD gate; also runs inside `make test`) |
| `make lint` | `ruff check` + `ruff format --check` |
| `make transcript` | scripted text-mode E2E conversation gate |
| `make eval` | full eval gate: `eval-hermetic` (hard) + `eval-live` (advisory) |
| `make eval-hermetic` | recorded-fixture DeepEval rubrics, no live agent drives (mandatory lane) |
| `make eval-live` | live agent/LLM drives caller personas (advisory — retried once, never fails the build) |
| `make latency` | stage + end-to-end latency bench, writes `data/latency/{ts}.json` (HARD gate) |
| `make booking-bench` | adaptive live booking-quality bench, writes `data/booking_quality/{ts}.json` |
| `make phone-debug` | Twilio CLI debug toolkit — `make phone-debug cmd="status"` |
| `make deploy` | `wrangler deploy` of the `app` to Cloudflare Containers |

Also: `./scripts/fresh_clone_smoke.sh` runs the fresh-clone rehearsal this feature's
gate requires (clone → env → compose up → healthchecks → `/healthz` → seeded-technician
check → booking round-trip; the last two skip with a warning until their owning
features land, see that script's header).

### Running the full test suite locally

The gate lanes below are what CI (and a release) checks. Run them from the repo root
with the venv present (`make` auto-prefers `.venv/bin/`). Lanes split into three groups
by what they need:

**Keyless — always runnable, hard gates:**

| Lane | Command | Notes |
|---|---|---|
| Unit/integration + stutter | `make test` | Runs the keyless stutter bench first (HARD gate — genuine barge-in must survive), then `pytest tests`. This is the main suite. |
| Stutter only | `make stutter` | The same phone-audio bench in isolation; writes `data/stutter/{ts}.json`. |
| Lint | `make lint` | `ruff check .` then `ruff format --check .`. Both must be clean. |
| Transcript E2E | `make transcript` | Scripted text-mode conversation gate; canary scenarios are expected to fail and are checked by the eval lanes. |

**Key-gated — SKIP loudly (never silently green) when the required key is absent:**

| Lane | Command | Keys required |
|---|---|---|
| Hermetic evals (mandatory) | `make eval-hermetic` | Judge key: `DEEPSEEK_API_KEY` (default) or `OPENAI_API_KEY` if `EVAL_JUDGE_PROVIDER=openai`. |
| Live evals (advisory) | `make eval-live` | Same judge key; failures are retried once and never fail the build. |
| Both eval lanes | `make eval` | As above. |
| Latency bench (hard gate) | `make latency` | Both `DEEPSEEK_API_KEY` (or `OPENAI_API_KEY` per `LLM_PROVIDER`) **and** `OPENAI_API_KEY` (STT/TTS). Skips if either is missing. |
| Booking-quality bench | `make booking-bench` | Live LLM key (per `LLM_PROVIDER`). |

Keys are read from the repo-root `.env`; a missing key prints a `WARNING: … skipping`
line — that is a **SKIP, not a pass** (see `tech-stack.md → Evaluation`).

The hard gate covers only the lanes we control: the **micro stages** (STT / LLM-TTFT /
TTS-cache) and the **Pipecat production lane** (end-of-speech → first audio through the
real voice pipeline). The **web and phone e2e lanes are ADVISORY** — measured, reported,
and marked `[ADVISORY]` in the table, but they never red the gate. Their submit/eos →
first-audio numbers are ~98% OpenAI full-context time-to-first-token, a third-party
latency we don't control that drifts intra-day; gating on it turns the bench into an
always-red signal-sink. The app-owned pipeline cost on those paths (sentence chunking,
filler, framing) stays hard-gated by the hermetic `tests/latency/` suite in `make test`.
Run `make latency args="--repeat 3"` for the noise-aware measurement envelope: it folds
N runs (median + noise% per lane) and writes `data/latency/{ts}-measurement.json`; the
hard verdict is unchanged (advisory lanes still don't gate). Pass `args="--repeat N"` to
forward any bench flag.

**Postgres-gated — scheduling/DB tests need the Compose db:**

Tests under `tests/scheduling/` (and the eval-live booking drive) require a reachable
Postgres. `make up` starts it; the Compose `db` is exposed at **`localhost:5433`**. Set
`DATABASE_URL` to point at it. These tests never touch the app DB named by
`DATABASE_URL`; they provision their own throwaway databases on the same server:
the scheduling suite uses a dedicated `<db>_test_scheduling` schema (drop/recreate
per test), and the booking-concurrency stress lane uses a separate `sears_stress`
database (TRUNCATE cleanup between cases). Without a reachable Postgres these tests
**skip** rather than fail — so when you want them to actually run, confirm the skip
count didn't swallow them.

### Debugging the phone channel (`make phone-debug`)

`scripts/twilio_debug.py` joins a failed call's four evidence surfaces — Twilio,
the ngrok tunnel, the app's structured `twilio.*` events, and the DB/recordings —
from one CLI (spec: `specs/features/2026-07-08-twilio-cli-debug/`). Read-only
except `wire --yes`; phone numbers print as last-4 and secrets are never echoed.

| Symptom | Toolkit | Raw twilio-cli equivalent |
|---|---|---|
| Call rings but nothing answers / dead air | `make phone-debug cmd="status"` (webhook mismatch?) | `twilio api:core:incoming-phone-numbers:fetch PN356e3d2a44afd34496997e66fb547da2 --properties voiceUrl,voiceMethod` |
| "Application error" spoken by Twilio | `make phone-debug cmd="alerts"` | `twilio api:monitor:alerts:list --limit 10` |
| Wired to a stale ngrok URL after restart | `make phone-debug cmd="wire --yes"` | `twilio api:core:incoming-phone-numbers:update PN356e… --voice-url https://<tunnel>/twilio/voice --voice-method POST` |
| Is Twilio even receiving my calls? | `make phone-debug cmd="calls --limit 5"` | `twilio api:core:calls:list --limit 5 --properties sid,status,duration,from` |
| Webhook 403s (signature) | `make phone-debug cmd="simulate"` locally | n/a (local; check `TWILIO_AUTH_TOKEN` is the Account Auth Token) |
| What happened during call X? | `make phone-debug cmd="call <CallSid>"` then `cmd="tail --call-sid <CallSid>"` | `twilio api:core:calls:fetch <CallSid>` + `docker compose logs app \| grep <CallSid>` |
| Where's the audio of call X? | `make phone-debug cmd="recordings --call-sid <CallSid>"` | `twilio api:core:recordings:list -o json`, then authenticated `curl …/Recordings/<RE>.mp3` |

## AI-assisted development (assignment §8)

This repo was built with AI pair-engineering (Claude Code) directed against a
spec-first harness I designed: the constitution and six feature triplets in `specs/`
(requirements → plan → validation), frozen cross-feature contracts
(`app/contracts.py`, tool signatures, prompt contracts), and deterministic gates
(stutter bench, latency budgets, booking-integrity suite, prompt static asserts) that
every merge had to pass. The agents wrote most of the lines; the architecture, the
contracts, the tradeoffs, and every accepted diff are mine to defend. The ~10-file
core I'd walk line-by-line in review: `app/voice/bot.py`, `app/agent/prompts.py`,
`app/agent/safety.py`, `app/tools/scheduling_tools.py`, `app/db/matching.py`,
`app/db/seed.py`, `app/db/models_scheduling.py`, `app/phone/webhook.py`,
`app/voice/turn_guard.py`, and `app/knowledge/loader.py`.

## Known limitations

- **Live phone number** — the Twilio number (**+1 (318) 646-8479**) is provisioned,
  wired to a `{PUBLIC_HOST}/twilio/voice` webhook, and **always available** for review
  calls against the hosted Cloudflare Worker
  (`sears-home-services-app.eeeew.workers.dev`). During local debugging the webhook can
  be temporarily re-pointed at an ephemeral cloudflared quick tunnel
  (`docs/twilio-webhook-setup.md`); it is restored to the hosted Worker afterwards.
- **No browser client** — the web UI was removed by design (the assignment is
  voice-first; its only browser surface is the backend-served Tier-3 upload page).
  The `/ws/call` text bridge remains as the hermetic test/eval surface for the
  agent loop.
- **No RAG over manufacturer manuals** — diagnostic knowledge is a deterministic, curated
  YAML lookup (six appliances × common issues), by design (`tech-stack.md` forbidden
  patterns) — not a stopgap, a scoping decision for a small, auditable knowledge base.
- **Slot times are zone-naive** — seeded slot hours live in a UTC column as business-hour
  labels and are spoken as US Central (the seeded Chicago/Dallas territory); true
  tz-aware storage/conversion is on the deferred list, not silently wrong-by-design.
- **Two phone-era directories** — `app/phone/` is the Twilio HTTP surface (webhook,
  TwiML, signature validation, latency budgets, call debug) from the original bridge;
  `app/voice/` is the Pipecat media pipeline that replaced the bridge's audio path
  (`app/phone/stt.py` survives only for the web channel's audio helper and the
  micro-latency bench — the live phone STT is Pipecat's). Both directories are
  live; the split is historical, kept because the HTTP half never needed rewriting.
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
