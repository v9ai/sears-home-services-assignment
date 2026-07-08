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
  uvicorn on `:8000`; restart policy.
- Multi-stage, non-root `Dockerfile`.
- Complete root README: quickstart ≤ 5 commands, architecture diagram (mermaid/ASCII),
  tier feature tour, spec-set reading guide, configuration table, known limitations.
- `docs/technical-design.md` — the 1–2 page design doc: architecture overview, key
  decisions distilled from the four feature specs (models + latency budget table, schema
  ERD sketch, tradeoffs incl. the Twilio adapter path and text-harness-first sequencing).
- `docs/demo-script.md` — a reviewer-followable 5-minute walkthrough.
- Final `.env.example`.

### Not included (deferred)
- CI/CD, cloud hosting, TLS — out of take-home scope.
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
3. **Deploy path**: `make up` is the launch; no cloud deploy. **Gate path**: fresh-clone
   smoke.

## Architecture impact
- Packaging and documentation only; no runtime behavior change. Invariant-preserving
  (this feature *is* mission non-negotiable 3 made durable).

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`.
- Constraints: `.env.example` is the secrets contract; no keys in git.
- Note: this phase can proceed in parallel from Phase 2 onward; the base Compose landed
  in Phase 1.
