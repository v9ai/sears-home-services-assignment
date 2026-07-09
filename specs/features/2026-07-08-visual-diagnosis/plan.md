# Visual Diagnosis (Tier 3) — Plan

Implement in dependency order; pause for review after group 4 (the vision merge is the
judgment-heavy part).

## 1. Schema + storage
- [x] Alembic rev 003: `image_uploads` per contract shapes (`alembic/versions/
      0003_visual_image_uploads.py`, `down_revision="0001_core"` per COORDINATION §2).
      `./data/uploads` Compose volume declared under Integration deltas (docker-compose.yml
      isn't owned by this feature); code creates the dir at runtime regardless
      (`os.makedirs(exist_ok=True)` in `app/uploads/routes.py`).

## 2. Email module
- [x] `EMAIL_BACKEND` switch: `cloudflare` (Cloudflare Email Service HTTP API) ·
      `smtp` (aiosmtplib) · `console` (offline demo, default). Dry-run/testable via
      `ConsoleEmailBackend.sent` list. `app/email/backend.py`, `app/email/templates.py`.
- [x] Case-file storage of the captured email lands via `send_image_upload_link`
      (`app/tools/visual_tools.py`) writing `case_file.customer.email`. The actual
      "ask + spell back for confirmation" conversational turn is system-prompt content
      owned by `app/agent` (voice-diagnostic-core) — flagged under Integration deltas.

## 3. Upload flow
- [x] `send_image_upload_link(email)` tool: token row + templated email (link to the
      FE `/upload/{token}` at `APP_BASE_URL`). `app/tools/visual_tools.py`.
- [x] `web/app/upload/[token]` page (Next.js, mobile-friendly file input, friendly
      error state for expired/used links) + backend `POST /api/upload/{token}` /
      `GET /api/upload/{token}` (size/mime allowlist, expiry, single-use — all
      enforced server-side, `app/uploads/routes.py`). EXIF-strip/resize left
      deferred (requirements.md's own open question) — would need Pillow, a new
      dependency this feature doesn't own; flagged under Integration deltas.

## 4. Vision analysis                                  ⏸ review after this group
- [x] `gpt-4o` vision call with JSON-schema response; prompt includes the case file
      (`app/vision/client.py`, `app/vision/schema.py`).
- [x] Merge analysis into the session case file (`app/vision/merge.py`,
      `app/vision/pipeline.py`); sets `image_uploads.status='analyzed'`. Reads/writes
      `sessions.case_file` via a minimal cross-feature `sessions_ref` Core table
      (`app/db/models_visual.py`) since no shared session-repository module exists yet;
      degrades gracefully (empty case file, no crash) if the sessions table isn't
      reachable, per COORDINATION §4.
- [x] Unit tests with mocked/injected vision analysis, no OpenAI calls
      (`tests/test_visual_pipeline.py`, `tests/test_visual_vision_merge.py`).

## 5. Agent wiring
- [x] `check_image_analysis()` tool (`app/tools/visual_tools.py`) — polls the latest
      upload for the session, folds `additional_steps` + visible issues into the case
      file and returns a natural-language summary as the tool result. The system-prompt
      guidance telling the LLM *when* to call it (owned by `app/agent`) is flagged
      under Integration deltas.
- [x] Follow-up email with findings when the session has already ended
      (`app/vision/pipeline.run_vision_pipeline`, tested in
      `tests/test_visual_pipeline.py::test_pipeline_emails_findings_when_session_already_ended`).

## 6. Gates
- [x] pytest: token expiry / single-use / oversize / bad-mime rejections; analysis-merge
      (`tests/test_visual_tokens.py`, `test_visual_upload_store.py`,
      `test_visual_upload_routes.py`, `test_visual_pipeline.py`, `test_visual_tools.py`,
      `test_visual_email.py`, `test_visual_vision_merge.py` — 39 tests, all green).
- [x] Extend `make transcript`: email capture spell-back scenario — landed as
      `evals/scenarios/visual/email_spellback.yaml` + fixture
      `evals/fixtures/transcripts/visual_email_spellback.json`, auto-discovered by
      `scripts/transcript_runner.py` and PASSing (gating sentinels present, so it runs
      rather than SKIPs).
- [x] Extend `make eval`: post-upload scenario through the DeepEval gate — landed as
      `evals/scenarios/visual/post_upload_incorporation.yaml` + fixture with the
      `photo_findings` rubric registered in `evals/metrics.py`; judged run itself is
      key-gated (`make eval` SKIPs without `DEEPSEEK_API_KEY` by design).
- [x] `make lint` + `make test` clean for all owned files (ran `ruff check .` /
      `ruff format --check .` / `pytest` directly — the `Makefile` targets themselves
      are still TODO stubs owned by testing-evals; see Integration deltas).
- [x] Tick roadmap Phase 3 `[x]` in `specs/constitution/roadmap.md` — done 2026-07-09:
      all Integration deltas landed, judged `make eval` GREEN (visual scenarios
      included), and a real GPT-4o Vision call verified through
      `app/vision/client.analyze_image`.

## Integration deltas (lead applies at merge; not made directly — none of these files
are owned by visual-diagnosis per COORDINATION §3)

1. **Mount the upload router** in `app/main.py` — **APPLIED 2026-07-08** (lead,
   Docker-storage change): `upload_router` included alongside `ws_router`.
2. **Compose volume** for `app/uploads/routes.py`'s `UPLOAD_DIR` — **APPLIED
   2026-07-08** (lead): named volume `uploads:/app/data/uploads` on the `app`
   service (named volume chosen over the originally-suggested bind mount; survives
   restarts, no host-path coupling). Docker-volume storage is the recorded decision —
   object storage (R2) rejected by user directive.
3. **`app/agent` system-prompt guidance** (owned by voice-diagnostic-core): (a) ask for
   an email + spell it back for confirmation when a photo would help, before calling
   `send_image_upload_link`; (b) call `check_image_analysis` when the caller says
   they've uploaded, and fold its returned summary / `additional_steps` into spoken
   troubleshooting guidance.
4. **Session-context key convention**: `app/tools/visual_tools.py` assumes the
   LlamaIndex workflow `Context` (auto-injected per-tool per `FunctionTool`'s
   `Context`-typed-param convention) exposes `ctx.store` keys `"session_id"` (str/UUID)
   and `"case_file"` (the `CaseFile` dict) — there's no frozen contract for this in
   `app/contracts.py`. Reconcile against whatever key names `app/agent`/`core_tools.py`
   actually use; rename in `app/tools/visual_tools.py` (`SESSION_ID_KEY` /
   `CASE_FILE_KEY` constants) if they differ.
5. **`sessions` table dependency**: `app/db/models_visual.py:sessions_ref` and
   `app/vision/pipeline.py` read/write `sessions.id` / `sessions.case_file` /
   `sessions.ended_at` (owned by voice-diagnostic-core's `0001_core`). Works standalone
   today (degrades to an empty case file, logged at debug level, if the table isn't
   reachable) but needs a real Alembic merge revision (`0001_core` + `0002_scheduling`
   + `0003_visual` all pre-allocated off different parents per COORDINATION §2) before
   the DB-level merge is actually exercised end-to-end.
6. **New pyproject dependency (not added)**: Pillow, only if EXIF-strip/resize on
   upload is implemented later (requirements.md's own deferred open question).
7. **`.env.example` additions (not made)**: `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME`
   / `SMTP_PASSWORD` if the `smtp` `EMAIL_BACKEND` path is ever exercised for real (only
   `console` and the `cloudflare` code path — untested against a live endpoint — are
   exercised today); `UPLOAD_DIR` if the default `data/uploads` relative path needs
   overriding; `CF_EMAIL_API_URL` if Cloudflare's actual send endpoint differs from the
   placeholder default in `app/email/backend.py`.
8. **Evals contract for testing-evals**: tools `send_image_upload_link(email) -> str` /
   `check_image_analysis() -> str` (both take a `Context` first-arg via LlamaIndex
   auto-injection, invisible to the tool schema); `check_image_analysis` return string
   cites `visible_issues`/`additional_steps` verbatim (for the G-Eval photo-findings
   rubric to match against) and, once analyzed, the case file gains
   `customer.email`, optionally `brand`/`appliance_type` (only if previously unset),
   deduped `steps_given` additions, and `safety_flag=True` if vision evidence contains
   hazard keywords (gas/spark/smoke/burn/fire/water near/exposed wire/electrical).
