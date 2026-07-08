# Deployment & Deliverables — Plan

## 0. PDF/spec alignment
- [x] PDF compliance matrix added to `requirements.md`: Tier 1 + Tier 2, Docker
      Compose, README, design doc, live phone number, and submission packet are required;
      Tier 3 visual diagnosis is explicitly optional/bonus.
- [x] Docker-first acceptance clarified: `docker compose up --build` is the primary
      reviewer path and must support a full Tier 1 + Tier 2 scheduling demo, not just
      service health.
- [x] Cloudflare status language tightened: dry-run verified, local live-verified, and
      hosted live-verified are distinct; no spec/doc may claim hosted live deployment
      from a Wrangler dry run alone.

## 1. Container hardening
- [x] Multi-stage Dockerfiles for `app` and `web` (builder + slim runtime, non-root).
- [x] Compose: `db` healthcheck gating `app`; `web` on `:3000`; named volumes;
      entrypoint migrate → seed → serve; restart policy.
      Locally verified earlier: `docker compose up --build` brought up db/app/web
      healthy; `/healthz` → 200; `:3000` → 200; non-root confirmed (`appuser` uid 1000
      in app, `nextjs` uid 1001 in web). Final PDF-complete verification must be
      re-run after the merged seed and booking flows are present.

## 1b. Cloudflare Containers deploy
- [ ] Neon project (provisioned: `damp-shape-82273628`, connection-verified): run
      `alembic upgrade heads` + seed against `DATABASE_URL_DIRECT` — real migrations
      (`0001_core`, `0002_scheduling`, `0003_visual`) have now merged, so this is
      runnable at integration.
      **Known issue (found 2026-07-08, FIXED same day)**: the dashboard connection
      strings carry `?sslmode=require&channel_binding=require`, which asyncpg rejects —
      now auto-translated by `app/db/base.py:normalize_asyncpg_url` (shared by
      `app/uploads/db.py`; unit-tested in `tests/test_db_url.py`).
- [x] Worker entry + `wrangler.toml` for `app` and `web`, reusing the Compose
      Dockerfiles; `make deploy`. `cloudflare/app-worker.ts` + `cloudflare/web-worker.ts`
      (`@cloudflare/containers` `Container` + `getContainer` singleton, proxying
      HTTP+WS straight through); `wrangler.app.toml` / `wrangler.web.toml` at repo root.
      Dry-run verified with `npx wrangler deploy --config wrangler.<app|web>.toml
      --dry-run`: both resolved config, built the container image from the *same*
      Dockerfiles Compose uses, and reported correct Durable Object bindings. This is
      **not** hosted live verification. Before hosted live can be claimed, app runtime
      vars/secrets must be passed into the container, and the web image must be built
      with `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` pointing at the deployed app
      Worker.
- [ ] Spec-to-config deltas before the next dry-run: add `instance_type = "basic"` to
      both container definitions; add `image_vars` for `NEXT_PUBLIC_API_URL` and
      `NEXT_PUBLIC_WS_URL` to the web container; pass required backend vars/secrets into
      `AppContainer` via `Container.envVars`; keep singleton routing and
      `max_instances = 1`.
- [ ] Re-run Cloudflare dry-run after those deltas: app dry-run builds the root
      Dockerfile and reports `APP_CONTAINER`; web dry-run builds `web/Dockerfile`,
      applies non-localhost `image_vars`, and reports `WEB_CONTAINER`.
- [ ] Hosted smoke: FE loads, one chat turn round-trips over WSS against the hosted
      backend. Requires a live Cloudflare account/`CLOUDFLARE_API_TOKEN`; the real
      agent is now merged. Hosted-live can only be claimed after app `/healthz`, web
      load, and browser WSS chat pass against deployed Cloudflare URLs.

## 2. Fresh-clone rehearsal
- [x] Scripted smoke: `scripts/fresh_clone_smoke.sh` — `git clone`s this repo to a
      scratch dir, `cp .env.example .env`, `docker compose up --build`, polls for
      db/app/web healthy, asserts `/healthz` 200 and `:3000` 200. Technician-count
      and booking-round-trip checks are written and wired (query `technicians` table;
      delegate to `scripts/transcript_runner.py`). The PDF-complete Docker-first gate
      requires these checks to pass without SKIP.
      Ran live end-to-end: PASS (`/healthz` 200, `:3000` 200, both SKIPs reported,
      overall PASS), then full teardown.
- [ ] Re-run after integration with no SKIPs: seeded technician count `>= 5` and one
      scripted Tier 2 booking round-trip must pass.

## 3. README rewrite
- [x] Quickstart (≤ 5 commands), architecture diagram, tier tour, spec reading guide,
      configuration table, known limitations (number provisioned — `+1 (318) 646-8479` —
      webhook wiring pending the Twilio phase). Tier-tour status column points at
      `roadmap.md` rather than a hardcoded per-tier claim, so it can't go stale as
      sibling agents land their features.

## 4. Technical design doc
- [x] `docs/technical-design.md` (~950 words incl. 3 tables + an ASCII ERD sketch, aimed
      at ≤ 2 printed pages): architecture (SessionBridge, tool auto-discovery,
      two-layer memory), ERD sketch, models + latency budget tables, 6 key tradeoffs,
      honest deferred-work list. Spot-checked against each feature's `requirements.md`
      Decisions section — no contradictions.

## 5. Demo script
- [x] `docs/demo-script.md`: 5-minute reviewer walkthrough (diagnose → book → photo),
      annotated with which mission non-negotiable each step demonstrates (safety
      interrupt, never-re-ask, booking integrity), plus an optional live-phone-number
      step.
- [x] `docs/SUBMISSION.md` (in requirements.md's "Included" scope and validation.md's
      manual checklist item 4, though not itemized in this plan originally — added
      here): repo link (placeholder — fill in before actually sending), test phone
      number, secure credential-sharing note (time-limited secret link, never
      email/Slack), contact + availability window (placeholder pending a real
      commitment).

## 6. Gates
- [x] Fresh-clone smoke baseline passed — `./scripts/fresh_clone_smoke.sh` previously
      ran a real clone + `docker compose up --build` and confirmed service health.
- [ ] Fresh-clone PDF gate complete — no scheduling-related checks may SKIP; seeded
      technician count and scripted booking must pass.
- [ ] Current `make lint` + `make test` rerun after spec/code integration.
- [ ] **Not ticking roadmap Phase 4 `[x]` yet.** Roadmap's own rule: "a phase is ticked
      `[x]` only when its `validation.md` Definition of Done holds." That DoD requires
      "all automated gates ... green," plus hosted integration before any Cloudflare
      live-deploy claim. Remaining gates: no-SKIP fresh-clone Tier 2 booking smoke,
      Cloudflare config deltas (`instance_type`, `image_vars`, `envVars`) + dry-runs,
      Cloudflare-hosted app `/healthz` + web load + WSS chat turn, and Twilio
      live-number acceptance in the telephony phase. Container hardening, README,
      design doc, demo script, and SUBMISSION.md are locally verified; current
      Cloudflare config is only partially specified/dry-run verified.

## Integration deltas

Spec-only alignment also updates the visual-diagnosis requirements to use the same
Docker upload volume name (`uploads`) as deployment/Compose. No runtime behavior is
changed by that spec correction.
For the record, a few things the lead (or a later deployment-deliverables pass) should
know about when the other five features land:

- **Run the fresh-clone rehearsal again after each feature merges.**
  `./scripts/fresh_clone_smoke.sh` already queries the `technicians` table and
  delegates to `scripts/transcript_runner.py` when present — it will start exercising
  those checks automatically once technician-scheduling and testing-evals land; no
  script changes needed, just re-run it.
- **Neon migrate+seed rehearsal (plan 1b, item 1)** needs real Alembic revisions
  (`0001_core`, `0002_scheduling`, `0003_visual` + the integration merge revision) to
  exist before `alembic upgrade head` against `DATABASE_URL_DIRECT` does anything
  meaningful — sequencing this is already covered by COORDINATION §5's integration
  order, not a new ask.
- **Hosted smoke (plan 1b item 3 / roadmap Phase 4 DoD)** needs a live Cloudflare
  account/`CLOUDFLARE_API_TOKEN` and the real agent merged. `make deploy` and both
  `wrangler.*.toml` are dry-run-verified; once credentials exist, first ensure backend
  env/secrets are propagated into the app container via `Container.envVars`, the web
  build receives the app Worker URL via `image_vars`, and both containers use
  `instance_type = "basic"`. Then run `make deploy` and the app-health/web-load/WSS
  chat checks. Only then tick roadmap Phase 4 `[x]`.
- **Considered, not done**: renaming the Postgres data volume mount from
  `/var/lib/postgresql/data` (foundation skeleton) to `/var/lib/postgresql` was a real
  bug fix (postgres:18-alpine requirement), already applied in `docker-compose.yml` —
  flagging here only so nobody reverts it thinking it was a stylistic change.
- **Optional nice-to-have, not requested by any triplet**: a `make smoke` alias
  wrapping `scripts/fresh_clone_smoke.sh` would match the existing Make-command
  ergonomics, but the tech-stack.md Make commands table doesn't list one, so it was
  left out rather than guessed in. Left as a suggestion, not an ask.
