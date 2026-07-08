# Deployment & Deliverables — Validation

## Automated
- [ ] Fresh-clone Compose smoke green: clone → `cp .env.example .env` + required keys →
      `docker compose config` → `docker compose up --build` → db/app/web healthy →
      `/healthz` 200 → web chat page renders on `:3000`.
- [ ] Docker-first PDF path green: seeded technician count is `>= 5`, the scripted
      Tier 2 booking round-trip completes, and no scheduling check is skipped.
- [ ] Cloudflare Containers dry-run green for both services: `wrangler deploy --dry-run`
      resolves config, builds the same Dockerfiles used by Compose, and reports the
      expected container Durable Object bindings.
- [ ] `make lint` + `make test` clean.

## Hosted integration
- [ ] With a real Cloudflare account / `CLOUDFLARE_API_TOKEN`, `make deploy` deploys
      `app` first and `web` second with frontend build args pointing at the app Worker.
- [ ] Cloudflare-hosted app returns `/healthz` 200.
- [ ] Cloudflare-hosted web loads and completes one chat turn over WSS against the
      Cloudflare-hosted backend.
- [ ] Twilio phase separately confirms the live phone number reaches the hosted
      `/twilio/voice` webhook and `/ws/twilio` bridge.

## Manual
1. A reader who has never seen the repo follows the README quickstart start-to-demo in
   under 10 minutes, with no verbal help.
2. `docs/technical-design.md` fits 2 pages printed and matches the specs (spot-check the
   decisions table against the feature requirements files).
3. `docs/demo-script.md` walkthrough completes: diagnose → book → photo loop.
4. `docs/SUBMISSION.md` covers the assignment's submission format: repo link, phone
   number, secure credential sharing, availability window.
5. Final PDF checklist is complete: source repo, Docker Compose launch, live phone
   number, README, technical design doc, secure credential handoff, expected live-system
   availability window.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Hosted integration gates are green before claiming Cloudflare live deployment.
- [ ] Deferred scope (CI/CD pipelines, durable upload storage, ngrok/Twilio Compose
      wiring) recorded in the roadmap backlog.
- [ ] Roadmap Phase 4 ticked `[x]`.
