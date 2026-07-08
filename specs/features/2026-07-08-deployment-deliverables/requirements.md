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
  UI and support a full Tier 1 + Tier 2 flow without any cloud account.
- Multi-stage, non-root Dockerfiles for `app` and `web`, built locally by Compose and
  buildable for Cloudflare Containers as Linux `amd64` images.
- **Cloudflare Containers deploy** of both `web` and `app`: Worker entry +
  `wrangler.toml` per service reusing the Compose Dockerfiles; `app` exposes public
  HTTP/WSS through the Worker-to-container proxy; `web` is a thin Worker-routed Next.js
  container; `NEXT_PUBLIC_*` frontend values are provided at image-build time; backend
  runtime config/secrets are provided through Wrangler vars/secrets and passed into the
  app container; `DATABASE_URL` points at **Neon** (pooled string for the app, direct
  string for migrations); deploy steps documented in the README (`make deploy`).
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
1. **Migrations + seed run in the app entrypoint, not a separate one-shot service** —
   fewer moving parts for a fresh-clone reviewer; idempotency makes re-runs safe.
2. **The design doc distills the specs, never contradicts them** — specs remain the
   source of truth; `docs/technical-design.md` is the reviewer-facing summary.
3. **Deploy path**: `make up` for local; `make deploy` (wrangler → Cloudflare
   Containers) for hosted. Workers terminate WSS, so the hosted backend serves
   `/ws/call` and the Phase 5 Twilio bridge without ngrok. **Gate path**: fresh-clone
   smoke + hosted smoke.
4. **Status language must be exact** — specs and docs distinguish planned, dry-run
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
- Constraints: `.env.example` is the secrets contract; no keys in git.
