# Deployment & Deliverables — Requirements

## Source
Roadmap Phase 4 (specs/constitution/roadmap.md). Assignment deliverables:
> Git repository · Docker Compose single-command launch · README (setup, architecture,
> configuration) · 1–2 page technical design document · live phone number (lands with
> the Twilio phase, `2026-07-08-telephony-twilio/`; number provisioned:
> `+1 (318) 646-8479`, webhook wiring pending).

## PDF compliance matrix

| PDF item | Owning spec | Required for final submission |
|---|---|---|
| Tier 1 diagnostic conversation: inbound call handling, appliance identification, symptom collection, troubleshooting, conversation memory | `2026-07-08-voice-diagnostic-core/` for agent behavior; `2026-07-08-telephony-twilio/` for live PSTN ingress | Yes |
| Tier 2 technician scheduling: technician DB, zip/specialty matching, availability, verbal confirmation | `2026-07-08-technician-scheduling/` plus this deployment gate's fresh-clone booking smoke | Yes |
| Tier 3 visual diagnosis: email capture, upload link, computer vision, enhanced troubleshooting | `2026-07-08-visual-diagnosis/` | Optional / bonus |
| Docker deployment: one command launches the system | This spec: `docker compose up --build` is the primary reviewer path | Yes |
| README documentation: setup, architecture, configuration | This spec | Yes |
| Technical design document: 1–2 pages of decisions/tradeoffs | This spec | Yes |
| Live phone number | `2026-07-08-telephony-twilio/` | Yes |
| Submission packet: repo link, phone number, credentials, availability window | This spec: `docs/SUBMISSION.md` | Yes |

## Scope

### Included
- Hardened `docker-compose.yml`: `db` healthcheck-gated, named volumes (`pgdata`,
  `uploads`), `app` entrypoint runs `alembic upgrade head` + idempotent seed, then
  uvicorn on `:8000`; `web` (Next.js) on `:3000`; restart policy. From a fresh clone,
  `cp .env.example .env && docker compose up --build` must expose a reviewer-ready demo
  UI and support a full Tier 1 + Tier 2 flow without any cloud account. Compose must
  not pass full `.env` into `web`; the frontend service receives only
  `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`.
- Multi-stage, non-root Dockerfiles for `app` and `web`, built locally by Compose and
  buildable for Cloudflare Containers as Linux `amd64` images.
- **Cloudflare Containers deploy** of both `web` and `app` per the contract below.
- Complete root README: quickstart ≤ 5 commands, architecture diagram (mermaid/ASCII),
  tier feature tour, spec-set reading guide, configuration table, known limitations.
- `docs/technical-design.md` — the 1–2 page design doc: architecture overview, key
  decisions distilled from the feature specs (models + latency budget table, schema
  ERD sketch, tradeoffs incl. the Twilio adapter path and text-harness-first
  sequencing), written "as if to a colleague" (assignment §6).
- `docs/SUBMISSION.md` — the assignment's submission format: repo link, test phone
  number, secure credential-sharing note, expected availability window for live testing.
- `docs/demo-script.md` — a reviewer-followable 5-minute walkthrough.
- Final `.env.example`.

### Cloudflare Containers contract
- Topology: two Worker-routed containers, `app` and `web`; no single combined image and
  no alternate cloud-only Dockerfiles.
- App service: `wrangler.app.toml` binds `AppContainer`; container image is the root
  `Dockerfile`; container port is `8000`; Worker routes all HTTP/WSS traffic with
  `getContainer(APP_CONTAINER, "singleton").fetch(request)`.
- Web service: `wrangler.web.toml` binds `WebContainer`; container image is
  `web/Dockerfile`; container port is `3000`; Worker routes all HTTP traffic with
  `getContainer(WEB_CONTAINER, "singleton").fetch(request)`.
- Capacity: `max_instances = 1` and `instance_type = "basic"` for both services.
  `standard-1` is only an explicit fallback if hosted smoke shows memory pressure;
  autoscaling, sharding, and random instance routing are out of scope for this demo.
- Build-time frontend vars: `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` are set via
  Cloudflare container `image_vars` for the `web` image so `next build` bakes deployed
  app URLs instead of localhost defaults. No backend secret may be available to the
  `web` Worker, `WebContainer`, or client bundle.
- Backend runtime vars: Worker vars/secrets alone are insufficient; the app Worker must
  pass required runtime config into the app container via `Container.envVars`.
- Required app container env names: `DATABASE_URL`, `DATABASE_URL_DIRECT`,
  `DEEPSEEK_API_KEY`, `LLM_PROVIDER`, `OPENAI_API_KEY`, `APP_BASE_URL`,
  `EMAIL_BACKEND`, `CF_EMAIL_API_TOKEN`, `EMAIL_FROM`, `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `PUBLIC_HOST`.
- Hosted database: Cloudflare does not run Postgres for this app; hosted deploys use
  Neon with pooled `DATABASE_URL` for runtime and direct `DATABASE_URL_DIRECT` for
  migrations/seed.
- Hosted status claims: "dry-run verified" means Wrangler config/image build passed;
  "hosted smoke verified" requires deployed app `/healthz`, deployed web load, and one
  browser WSS chat turn through the app Worker.

### Secrets & API safety contract
- Source control: `.env`, `.env.*`, private keys, credential exports, and local secret
  manager dumps are never tracked. `.env.example` remains the committed contract and
  contains fake placeholders only.
- Frontend isolation: only `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` may be present
  in `web` Compose config, `web` Cloudflare `image_vars`, frontend runtime env, or
  client build output.
- Backend-only secrets: model API keys, Neon URLs, Twilio auth token, SMTP password,
  Cloudflare Email token, and ngrok token may be present only in local `.env`, host env,
  Wrangler secrets, and the backend app container env.
- Logging/redaction: logs and error messages may name missing env vars but must not emit
  secret values, `Authorization`/`Bearer` headers, SMTP passwords, Twilio auth tokens,
  API tokens, or DB URLs with passwords.
- Credential handoff: reviewer credentials are shared only through a time-limited secret
  link or reviewer-provided env vars; docs and submission materials mention names and
  setup steps only.

### Not included (deferred)
- CI/CD pipelines — out of take-home scope; deploys are `wrangler` invocations.
- Durable hosted upload storage — upload storage is the Docker named volume
  `uploads` **by decision** (user directive 2026-07-08; object storage incl.
  Cloudflare R2 rejected). On Cloudflare Containers the disk is ephemeral — accepted
  limitation, documented in the README known-limitations section.
- Twilio webhook wiring and live-call acceptance — lands with
  `2026-07-08-telephony-twilio/`; this spec only ensures the hosted backend can expose
  the required public HTTPS/WSS endpoints.

### Contract shapes
- `docker-compose.yml`, `Dockerfile`, `web/Dockerfile`, `wrangler.app.toml`,
  `wrangler.web.toml`, `cloudflare/*-worker.ts`, `README.md`,
  `docs/technical-design.md`, `docs/demo-script.md`, `docs/SUBMISSION.md`,
  `.env.example`.
- Gate: fresh-clone smoke script (clone to temp dir → `cp .env.example .env` + keys →
  `docker compose up --build` → `/healthz` 200 → web renders → seeded technician count
  `>= 5` → one scripted text-mode booking round-trip).

## Decisions
1. **Docker-first review path** — the local Docker Compose demo is the canonical way to
   judge PDF compliance because it is deterministic, self-contained, and does not depend
   on reviewer cloud credentials.
2. **Migrations + seed run in the app entrypoint, not a separate one-shot service** —
   fewer moving parts for a fresh-clone reviewer; idempotency makes re-runs safe.
3. **The design doc distills the specs, never contradicts them** — specs remain the
   source of truth; `docs/technical-design.md` is the reviewer-facing summary.
4. **Deploy path**: `make up` for local; `make deploy` (wrangler → Cloudflare
   Containers) for hosted. Workers terminate WSS, so the hosted backend serves
   `/ws/call` and the Phase 5 Twilio bridge without ngrok. **Gate path**: fresh-clone
   smoke + Cloudflare dry-run + hosted smoke.
5. **Status language must be exact** — specs and docs distinguish planned, dry-run
   verified, local live-verified, and hosted live-verified states; no "verified live"
   claim may refer only to a dry run.

## Architecture impact
- Packaging and documentation only; no runtime behavior change. Invariant-preserving
  (this feature *is* mission non-negotiable 3 made durable).

## Parallel execution (COORDINATION.md §3–4)
- Owned paths: `Dockerfile*`, `docker-compose.yml` hardening, `wrangler*.toml`,
  `README.md`, `docs/`.
- Stub seam: hardens containers/docs against the foundation skeleton (`/healthz`
  suffices for smoke); final README/design-doc pass and hosted smoke land at
  integration step 4, after features merge.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`.
- Constraints: `.env.example` is the secrets contract; no keys in git; frontend gets
  public env only; secret values are never logged or documented.
