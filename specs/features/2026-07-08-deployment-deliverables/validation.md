# Deployment & Deliverables — Validation

## Automated
- [ ] Fresh-clone smoke script green (clone → env → `docker compose up` → `/healthz`
      200 → web chat page renders on `:3000` → seeded technician count → scripted
      booking round-trip).
- [ ] Vercel production FE loads and completes a chat turn against the hosted backend.
- [ ] `make lint` + `make test` clean.

## Manual
1. A reader who has never seen the repo follows the README quickstart start-to-demo in
   under 10 minutes, with no verbal help.
2. `docs/technical-design.md` fits 2 pages printed and matches the specs (spot-check the
   decisions table against the feature requirements files).
3. `docs/demo-script.md` walkthrough completes: diagnose → book → photo loop.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Deferred scope (CI/CD, hosting, TLS) recorded as roadmap non-goals/backlog.
- [ ] Roadmap Phase 4 ticked `[x]`.
