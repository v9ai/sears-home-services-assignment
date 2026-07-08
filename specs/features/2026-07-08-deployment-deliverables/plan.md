# Deployment & Deliverables — Plan

## 1. Container hardening
- [x] Multi-stage Dockerfiles for `app` and `web` (builder + slim runtime, non-root).
- [x] Compose: `db` healthcheck gating `app`; `web` on `:3000`; named volumes;
      entrypoint migrate → seed → serve; restart policy.
      Verified live: `docker compose up --build` brings up db (healthy) → app
      (healthy, entrypoint ran `alembic upgrade heads` then skipped seed gracefully
      since `app.db.seed` doesn't exist yet) → web (healthy); `/healthz` → 200;
      `:3000` → 200. Non-root confirmed (`appuser` uid 1000 in app, `nextjs` uid 1001
      in web). Found and fixed a real bug: `postgres:18-alpine` refuses to start
      against a `.../data`-mounted volume (18+ changed to a pg_ctlcluster-style
      layout) — remounted `pgdata` at `/var/lib/postgresql` instead.

## 1b. Cloudflare Containers deploy
- [ ] **Deferred to integration** — Neon project (provisioned: `damp-shape-82273628`,
      connection-verified): run `alembic upgrade head` + seed against
      `DATABASE_URL_DIRECT`. Blocked on real migrations (`0001_core`, `0002_scheduling`)
      landing from voice-diagnostic-core / technician-scheduling; nothing to run yet.
- [x] Worker entry + `wrangler.toml` for `app` and `web`, reusing the Compose
      Dockerfiles; `make deploy`. `cloudflare/app-worker.ts` + `cloudflare/web-worker.ts`
      (`@cloudflare/containers` `Container` + `getContainer` singleton, proxying
      HTTP+WS straight through); `wrangler.app.toml` / `wrangler.web.toml` at repo root.
      Verified live with `npx wrangler deploy --config wrangler.<app|web>.toml
      --dry-run`: both resolved config, built the container image from the *same*
      Dockerfiles Compose uses, and reported correct Durable Object bindings — no
      Cloudflare account needed for this level of validation. Secrets/vars notes and
      the NEXT_PUBLIC_* build-arg ordering (deploy `app` first, then build `web` with
      its URL) are documented as comments in the wrangler files.
- [ ] **Deferred to integration** (COORDINATION §4 stub seam) — Hosted smoke: FE loads,
      one chat turn round-trips over WSS against the hosted backend. Requires a live
      Cloudflare account/`CLOUDFLARE_API_TOKEN` and the real agent (voice-diagnostic-core)
      merged; not available in this worktree. `make deploy` is ready to run once both
      are in place.

## 2. Fresh-clone rehearsal
- [x] Scripted smoke: `scripts/fresh_clone_smoke.sh` — `git clone`s this repo to a
      scratch dir, `cp .env.example .env`, `docker compose up --build`, polls for
      db/app/web healthy, asserts `/healthz` 200 and `:3000` 200. Technician-count
      and booking-round-trip checks are written and wired (query `technicians` table;
      delegate to `scripts/transcript_runner.py`) but SKIP with a warning today since
      technician-scheduling/testing-evals haven't landed yet (COORDINATION §4 stub
      seam) — no changes needed to this script once they do.
      Ran live end-to-end: PASS (`/healthz` 200, `:3000` 200, both SKIPs reported,
      overall PASS), then full teardown.

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
- [ ] Fresh-clone smoke green.
- [ ] `make lint` + `make test` clean.
- [ ] Tick roadmap Phase 4 `[x]` in `specs/constitution/roadmap.md`.
