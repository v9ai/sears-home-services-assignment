# Deployment & Deliverables — Requirements

## Source
Roadmap Phase 4 (specs/constitution/roadmap.md). Assignment deliverables:
> Git repository · Docker Compose single-command launch · README (setup, architecture,
> configuration) · 1–2 page technical design document · live phone number (lands with
> the Twilio phase, `2026-07-08-telephony-twilio/`).

## Scope

### Included
- Hardened `docker-compose.yml`: `db` healthcheck-gated, named volumes (`pgdata`,
  `uploads`), `app` entrypoint runs `alembic upgrade head` + idempotent seed, then
  uvicorn on `:8000`; `web` (Next.js) on `:3000`; restart policy.
- Multi-stage, non-root Dockerfiles for `app` and `web`.
- **Cloudflare Containers deploy** of both `web` and `app`: Worker entry +
  `wrangler.toml` per service reusing the Compose Dockerfiles; `NEXT_PUBLIC_*` and
  backend env configured as wrangler vars/secrets; `DATABASE_URL` pointed at **Neon**
  (pooled string for the app, direct string for migrations); deploy steps documented in
  the README (`make deploy`).
- Complete root README: quickstart ≤ 5 commands, architecture diagram (mermaid/ASCII),
  tier feature tour, spec-set reading guide, configuration table, known limitations.
- `docs/technical-design.md` — the 1–2 page design doc: architecture overview, key
  decisions distilled from the four feature specs (models + latency budget table, schema
  ERD sketch, tradeoffs incl. the Twilio adapter path and text-harness-first sequencing).
- `docs/demo-script.md` — a reviewer-followable 5-minute walkthrough.
- Final `.env.example`.

### Not included (deferred)
- CI/CD pipelines — out of take-home scope; deploys are `wrangler` invocations.
- Durable hosted upload storage — container disk is ephemeral on Cloudflare; acceptable
  for the demo, R2 recorded in the backlog.
- ngrok/Twilio wiring in Compose — lands with `2026-07-08-telephony-twilio/`.

### Contract shapes
- `docker-compose.yml`, `Dockerfile`, `README.md`, `docs/technical-design.md`,
  `docs/demo-script.md`, `.env.example`.
- Gate: fresh-clone smoke script (clone to temp dir → `cp .env.example .env` + keys →
  `docker compose up` → `/healthz` 200 → seeded technician count → one scripted
  text-mode booking round-trip).

## Decisions
1. **Migrations + seed run in the app entrypoint, not a separate one-shot service** —
   fewer moving parts for a fresh-clone reviewer; idempotency makes re-runs safe.
2. **The design doc distills the specs, never contradicts them** — specs remain the
   source of truth; `docs/technical-design.md` is the reviewer-facing summary.
3. **Deploy path**: `make up` for local; `make deploy` (wrangler → Cloudflare
   Containers) for hosted. Workers terminate WSS, so the hosted backend serves
   `/ws/call` and the Phase 5 Twilio bridge without ngrok. **Gate path**: fresh-clone
   smoke + hosted smoke.

## Architecture impact
- Packaging and documentation only; no runtime behavior change. Invariant-preserving
  (this feature *is* mission non-negotiable 3 made durable).

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`.
- Constraints: `.env.example` is the secrets contract; no keys in git.
- Note: this phase can proceed in parallel from Phase 2 onward; the base Compose landed
  in Phase 1.
