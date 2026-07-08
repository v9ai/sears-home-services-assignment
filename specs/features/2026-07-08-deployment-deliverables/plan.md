# Deployment & Deliverables — Plan

## 1. Container hardening
- [ ] Multi-stage Dockerfiles for `app` and `web` (builder + slim runtime, non-root).
- [ ] Compose: `db` healthcheck gating `app`; `web` on `:3000`; named volumes;
      entrypoint migrate → seed → serve; restart policy.

## 1b. Cloudflare Containers deploy
- [ ] Neon project: create DB, run `alembic upgrade head` + seed against the direct
      connection string.
- [ ] Worker entry + `wrangler.toml` for `app` and `web`, reusing the Compose
      Dockerfiles; wrangler vars/secrets (`NEXT_PUBLIC_*`, `OPENAI_API_KEY`,
      `DATABASE_URL` → Neon pooled string); `make deploy`.
- [ ] Hosted smoke: FE loads, one chat turn round-trips over WSS against the hosted
      backend.

## 2. Fresh-clone rehearsal
- [ ] Scripted smoke: clone to a temp dir, `cp .env.example .env`, add keys,
      `docker compose up`, assert `/healthz` 200, seeded technician count, one
      text-mode booking round-trip.

## 3. README rewrite
- [ ] Quickstart (≤ 5 commands), architecture diagram, tier tour, spec reading guide,
      configuration table, known limitations (number provisioned — `+1 (318) 646-8479` —
      webhook wiring pending the Twilio phase).

## 4. Technical design doc
- [ ] `docs/technical-design.md` (≤ 2 printed pages): architecture, decisions table
      distilled from the feature specs, latency budget, ERD sketch, tradeoffs.

## 5. Demo script
- [ ] `docs/demo-script.md`: 5-minute reviewer walkthrough (diagnose → book → photo).

## 6. Gates
- [ ] Fresh-clone smoke green.
- [ ] `make lint` + `make test` clean.
- [ ] Tick roadmap Phase 4 `[x]` in `specs/constitution/roadmap.md`.
