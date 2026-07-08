# Deployment & Deliverables — Plan

## 1. Container hardening
- [ ] Multi-stage `Dockerfile` (builder + slim runtime, non-root user).
- [ ] Compose: `db` healthcheck gating `app`; named volumes; entrypoint
      migrate → seed → serve; restart policy.

## 2. Fresh-clone rehearsal
- [ ] Scripted smoke: clone to a temp dir, `cp .env.example .env`, add keys,
      `docker compose up`, assert `/healthz` 200, seeded technician count, one
      text-mode booking round-trip.

## 3. README rewrite
- [ ] Quickstart (≤ 5 commands), architecture diagram, tier tour, spec reading guide,
      configuration table, known limitations (phone number pending the Twilio phase).

## 4. Technical design doc
- [ ] `docs/technical-design.md` (≤ 2 printed pages): architecture, decisions table
      distilled from the feature specs, latency budget, ERD sketch, tradeoffs.

## 5. Demo script
- [ ] `docs/demo-script.md`: 5-minute reviewer walkthrough (diagnose → book → photo).

## 6. Gates
- [ ] Fresh-clone smoke green.
- [ ] `make lint` + `make test` clean.
- [ ] Tick roadmap Phase 4 `[x]` in `specs/constitution/roadmap.md`.
