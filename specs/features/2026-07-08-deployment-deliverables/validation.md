# Deployment & Deliverables — Validation

## Automated
- [ ] Fresh-clone Compose smoke green: clone → `cp .env.example .env` + required keys →
      `docker compose config` → `docker compose up --build` → db/app/web healthy →
      `/healthz` 200 → web chat page renders on `:3000`.
- [ ] Docker-first PDF path green: seeded technician count is `>= 5`, the scripted
      Tier 2 booking round-trip completes, and no scheduling check is skipped.
- [ ] Cloudflare static config check green: both `wrangler.*.toml` files declare
      `[[containers]]`, `instance_type = "basic"`, `max_instances = 1`, Durable Object
      bindings, and Durable Object migrations; `wrangler.web.toml` declares
      `image_vars` for `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`.
- [ ] Cloudflare app dry-run green: `wrangler deploy --dry-run --config
      ../wrangler.app.toml` resolves config, builds the root `Dockerfile`, and reports
      the expected `APP_CONTAINER` Durable Object binding.
- [ ] Cloudflare web dry-run green: `wrangler deploy --dry-run --config
      ../wrangler.web.toml` resolves config, builds `web/Dockerfile`, and reports the
      expected `WEB_CONTAINER` Durable Object binding with non-localhost frontend URLs.
- [ ] Static secret-safety check green: `git ls-files` contains no `.env`, private key,
      credential export, or secret dump; tracked files contain no real token-shaped
      OpenAI, DeepSeek, Twilio Auth Token, Neon URL, Cloudflare token, SMTP password, or
      `Authorization: Bearer` value.
- [ ] Compose frontend env check green: rendered `docker compose config` proves `web`
      receives only `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`, never full `.env` or
      backend secret names.
- [ ] Redaction/static logging check green: app code and scripts do not log
      `Authorization`, `Bearer`, API key, auth token, SMTP password, or database URL
      values; DB URL rendering outside driver setup hides passwords.
- [ ] `make lint` + `make test` clean.

## Hosted integration
- [x] `make deploy` RUN 2026-07-08 (wrangler OAuth): `app` deployed (version
      b49fa743…, envVars contract v3 incl. the OPENAI_LLM_MODEL pin) then `web`
      (version 6934deca…) with `image_vars` baked to the app Worker URL.
- [ ] App Worker secrets/vars are passed into the container through `Container.envVars`;
      a secret existing only on the Worker does not satisfy this gate.
- [ ] Web Worker and `WebContainer` have no secrets: only public `image_vars` are
      present, and frontend build artifacts contain no backend secret names or values.
- [x] Cloudflare-hosted app `/healthz` 200 (first cold request 500 during the
      entrypoint's Neon migrate+seed window — expected; warm 200 ×3, verified
      2026-07-08).
- [x] Hosted WSS chat turn PASSED 2026-07-08 (scripted client on `wss://…/ws/call`):
      greeting at 1.21 s, spoken filler, 4 reply sentences, 138 TTS audio chunks,
      state frames; hosted `/api/recordings` serves real Neon sessions; web
      `/recordings` page 200.
- [ ] Twilio phase separately confirms the live phone number reaches the hosted
      `/twilio/voice` webhook and `/ws/twilio` bridge.

## Cloudflare failure criteria
- Hosted-live cannot be claimed when only Wrangler dry-run has passed.
- Hosted-live cannot be claimed if `web` was built with localhost `NEXT_PUBLIC_*`
  values.
- Hosted-live cannot be claimed if app secrets are configured on the Worker but not
  propagated into the container.
- Hosted-live cannot be claimed if any backend secret is reachable from `web`, appears
  in browser-delivered JS, appears in logs, or appears in docs/submission materials.
- Hosted-live cannot be claimed until app `/healthz`, web load, and browser WSS chat
  all pass against deployed Cloudflare URLs.

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
6. Credential handoff docs describe time-limited secret links or reviewer-provided env
   vars only; no plaintext key value is present in README, docs, specs, shell history
   snippets, screenshots, or submission text.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Hosted integration gates are green before claiming Cloudflare live deployment.
- [ ] Secret-safety gates above are green before any reviewer handoff.
- [ ] Deferred scope (CI/CD pipelines, durable upload storage, ngrok/Twilio Compose
      wiring) recorded in the roadmap backlog.
- [ ] Roadmap Phase 4 ticked `[x]`.
