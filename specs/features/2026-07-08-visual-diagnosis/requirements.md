# Visual Diagnosis (Tier 3) — Requirements

## Source
Roadmap Phase 3 (specs/constitution/roadmap.md). Assignment Tier 3:
> Email capture during the call · unique image-upload link sent by email · appliance /
> visible-issue recognition with computer vision · enhanced troubleshooting from the
> visual information.

## Scope

### Included
- In-call email capture: the agent asks for the email when a photo would help, spells it
  back for confirmation, stores it in the case file.
- `send_image_upload_link(email)` tool: creates a tokenized upload row and emails
  `{APP_BASE_URL}/upload/{token}` — `APP_BASE_URL` is the **frontend base URL** (the
  Cloudflare-hosted `web` in production, `localhost:3000` locally); the page relays to
  the backend API.
- Mobile-friendly upload page `web/app/upload/[token]` (Next.js) posting to the backend
  `POST /api/upload/{token}` (multipart; 10 MB cap; jpeg/png/webp allowlist; expiry +
  single-use enforced server-side).
- Image storage on a local Docker volume (`./data/uploads`).
- GPT-4o vision analysis (JSON-schema response) merged into the session case file.
- `check_image_analysis()` agent tool so a still-live call incorporates the findings;
  follow-up email with findings if the call has ended.
- Alembic rev 003: `image_uploads`.

### Not included (deferred)
- MMS ingestion — needs telephony (Twilio phase).
- Multi-image galleries; S3/object storage (local volume suffices for the take-home).

### Contract shapes
- Alembic rev 003: `image_uploads(id, session_id FK, email, token varchar UNIQUE,
  image_path, status text CHECK IN ('pending','uploaded','analyzed','expired'),
  vision_analysis jsonb, created_at, expires_at)`.
- Vision output JSON: `{appliance_detected, brand_guess,
  visible_issues: [{issue, confidence, evidence}],
  matches_reported_symptoms: bool, additional_steps: [str]}`.
- Email template with the upload link; env `EMAIL_BACKEND` selects the provider.
- Gates: `make test` (token lifecycle, mocked vision), `make transcript` extension.

## Decisions
1. **Token = 128-bit `secrets.token_urlsafe` stored in the row, not a JWT** — revocable,
   single-use, 24 h expiry, no key management to review. `UPLOAD_TOKEN_SECRET` stays
   reserved if signing is later wanted.
2. **Vision = `gpt-4o` chat-with-image with JSON-schema response format** — same vendor,
   zero extra infra; the prompt includes the case file so the model *confirms or
   contradicts* reported symptoms rather than diagnosing blind. Analysis is advisory:
   merged as evidence, the agent re-runs decision-tree logic against it.
3. **Email = Resend HTTP API (flagged decision)** — one POST, free tier, no SMTP ports
   blocked in Docker. `aiosmtplib` SMTP fallback and a console-log backend (offline demo)
   behind `EMAIL_BACKEND`.
4. **Live-call integration = polling tool, not WS push** — the agent calls
   `check_image_analysis` when the caller says they've uploaded; push deferred for
   simplicity.
5. **Gate path**: token lifecycle + mocked-vision merge tests; transcript extension.

## Architecture impact
- Adds upload routes, one email module, one vision service, two agent tools, rev 003.
  Invariant-preserving.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; builds on Phase 1 case-file
  shapes and Phase 2's customer email usage.
- Constraints: secrets via env only; never re-ask an email already captured.
- Open question (deferred): EXIF-strip/resize on upload — do at upload time if trivial.
