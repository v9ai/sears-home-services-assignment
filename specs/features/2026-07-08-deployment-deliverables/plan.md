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
      Verified live with `npx wrangler deploy --config wrangler.<app|web>.toml
      --dry-run`: both resolved config, built the container image from the *same*
      Dockerfiles Compose uses, and reported correct Durable Object bindings — no
      Cloudflare account needed for this level of validation. Secrets/vars notes and
      the NEXT_PUBLIC_* build-arg ordering (deploy `app` first, then build `web` with
      its URL) are documented as comments in the wrangler files.
- [ ] Hosted smoke: FE loads, one chat turn round-trips over WSS against the hosted
      backend. Requires a live Cloudflare account/`CLOUDFLARE_API_TOKEN`; the real
      agent is now merged. `make deploy` is ready to run once credentials are in place.

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
- [x] Fresh-clone smoke green — `./scripts/fresh_clone_smoke.sh` ran clean end-to-end
      (see Group 2 note): real `git clone`, `docker compose up --build`, all three
      services healthy, `/healthz` 200, `:3000` 200, two checks SKIP pending sibling
      features.
- [x] `make lint` + `make test` run clean (exit 0) — but both are still the
      foundation's no-op TODO stubs owned by testing-evals, so "clean" today only means
      "doesn't error," not "passed a real gate." Re-run once testing-evals lands real
      bodies; not this feature's gate to fill in (COORDINATION §3).
- [ ] **Not ticking roadmap Phase 4 `[x]` yet.** Roadmap's own rule: "a phase is ticked
      `[x]` only when its `validation.md` Definition of Done holds." That DoD requires
      "all automated gates ... green," including "Cloudflare-hosted FE loads and
      completes a chat turn over WSS against the Cloudflare-hosted backend" — not
      achievable in this worktree (no live Cloudflare account, no real agent merged
      yet; COORDINATION §4/§5 explicitly defer this to integration step 4, after
      voice-diagnostic-core/scheduling/visual-diagnosis merge). Container hardening,
      Cloudflare deploy config, README, design doc, demo script, and SUBMISSION.md are
      all done and verified against the current (stub) system; the remaining DoD item
      is a follow-up pass once the rest of the system is real. See "Integration
      deltas" below and the final report to `main`.

## Integration deltas

Nothing required outside this feature's owned paths — no shared-file edits declared.
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
  `wrangler.*.toml` are ready and dry-run-verified; once credentials exist, run
  `make deploy` then the FE-loads-and-completes-a-chat-turn check, then tick roadmap
  Phase 4 `[x]`.
- **Considered, not done**: renaming the Postgres data volume mount from
  `/var/lib/postgresql/data` (foundation skeleton) to `/var/lib/postgresql` was a real
  bug fix (postgres:18-alpine requirement), already applied in `docker-compose.yml` —
  flagging here only so nobody reverts it thinking it was a stylistic change.
- **Optional nice-to-have, not requested by any triplet**: a `make smoke` alias
  wrapping `scripts/fresh_clone_smoke.sh` would match the existing Make-command
  ergonomics, but the tech-stack.md Make commands table doesn't list one, so it was
  left out rather than guessed in. Left as a suggestion, not an ask.
