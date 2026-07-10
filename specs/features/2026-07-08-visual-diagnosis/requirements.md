# Visual Diagnosis (Tier 3) — Requirements

## Source
Roadmap Phase 3 (specs/constitution/roadmap.md). Assignment Tier 3:
> Email capture during the call · unique image-upload link sent by email · appliance /
> visible-issue recognition with computer vision · enhanced troubleshooting from the
> visual information.

## Scope

> **As-built note (2026-07-11).** The `web/` Next.js frontend was removed by design; the
> upload page is now served **from the backend** at `GET /upload/{token}` as static HTML
> (`app/uploads/routes.py`), with the token read client-side and posted to the upload API.
> `APP_BASE_URL` is therefore the backend's own public base URL, not a separate frontend
> URL (`.env.example`: `http://localhost:8000` locally). The requirement's intent — a
> unique tokenized upload link emailed to the caller — is unchanged; only the delivery
> mechanism differs. The bullets below are stated against that shipped design.

### Included
- In-call email capture: the agent asks for the email when a photo would help, spells it
  back for confirmation, stores it in the case file.
- `send_image_upload_link(email)` tool: creates a tokenized upload row and emails
  `{APP_BASE_URL}/upload/{token}` — `APP_BASE_URL` is the **backend's own public base
  URL** (the backend serves the upload page itself; `localhost:8000` locally, per
  `.env.example`).
- Mobile-friendly upload page served **by the backend** at `GET /upload/{token}` (static
  HTML in `app/uploads/routes.py`; the token is read client-side and posted to
  `POST /api/upload/{token}` — multipart; 10 MB cap; jpeg/png/webp allowlist; expiry +
  single-use enforced server-side).
- Image storage on a local Docker volume (`./data/uploads`).
- GPT-4o vision analysis (JSON-schema response) merged into the session case file.
- `check_image_analysis()` agent tool so a still-live call incorporates the findings;
  follow-up email with findings if the call has ended.
- Alembic rev 003: `image_uploads`.

### Not included (deferred)
- MMS ingestion — needs telephony (Twilio phase).
- Multi-image galleries.
- S3/object storage incl. Cloudflare R2 — **rejected** (user directive 2026-07-08);
  the Docker named volume (`uploads`) is the storage decision.

### Contract shapes
- Alembic rev 003: `image_uploads(id, session_id FK, email, token varchar UNIQUE,
  image_path, status text CHECK IN ('pending','uploaded','analyzed','expired'),
  vision_analysis jsonb, created_at, expires_at)`.
- Vision output JSON: `{appliance_detected, brand_guess,
  visible_issues: [{issue, confidence, evidence}],
  matches_reported_symptoms: bool, additional_steps: [str]}`.
- Email template with the upload link; env `EMAIL_BACKEND` selects the provider.
- Gates: `make test` (token lifecycle, mocked vision), `make transcript` extension,
  `make eval` extension.

## Decisions
1. **Token = 128-bit `secrets.token_urlsafe` stored in the row, not a JWT** — revocable,
   single-use, 24 h expiry, no key management to review. `UPLOAD_TOKEN_SECRET` stays
   reserved if signing is later wanted.
2. **Vision = GPT-4 Vision (assignment option), served by `gpt-4o` chat-with-image with
   JSON-schema response format** — `gpt-4o` is the current GPT-4-class vision API (the
   `gpt-4-vision-preview` endpoint is retired); same vendor, zero extra infra. The
   prompt includes the case file so the model *confirms or contradicts* reported
   symptoms rather than diagnosing blind. Analysis is advisory: merged as evidence, the
   agent re-runs decision-tree logic against it.
3. **Email = Cloudflare Email Service (user directive, 2026-07-08)** — the upload-link
   email sends through Cloudflare's transactional email API, keeping email on the same
   platform that hosts the containers (one vendor, one token). Sender
   domain/address verified in the Cloudflare dashboard. `aiosmtplib` SMTP fallback and
   a console-log backend (offline demo) stay behind `EMAIL_BACKEND`
   (`cloudflare` | `smtp` | `console`).
4. **Live-call integration = polling tool, not WS push** — the agent calls
   `check_image_analysis` when the caller says they've uploaded; push deferred for
   simplicity.
5. **Gate path**: token lifecycle + mocked-vision merge tests; transcript extension;
   `make eval` extension (Knowledge Retention on the captured email; G-Eval
   photo-findings rubric — the agent's post-upload guidance references the vision
   analysis rather than ignoring it).

## Architecture impact
- Adds upload routes, one email module, one vision service, two agent tools, rev 003.
  Invariant-preserving.

## Parallel execution (COORDINATION.md §3–4)
- Owned paths: `app/email/`, `app/uploads/`, `app/vision/`, `app/tools/visual_tools.py`,
  `app/db/models_visual.py`, `alembic/versions/0003_visual*`, `web/app/upload/`.
- Stub seam: routes/email/vision run standalone against a faked session row;
  `EMAIL_BACKEND=console`; vision mocked in tests. Rev id `0003_visual` pre-allocated.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; builds on Phase 1 case-file
  shapes and Phase 2's customer email usage.
- Constraints: secrets via env only; never re-ask an email already captured.
- Open question (deferred): EXIF-strip/resize on upload — do at upload time if trivial.
