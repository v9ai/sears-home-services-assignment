# Visual Diagnosis (Tier 3) — Plan

Implement in dependency order; pause for review after group 4 (the vision merge is the
judgment-heavy part).

## 1. Schema + storage
- [ ] Alembic rev 003: `image_uploads` per contract shapes; `./data/uploads` volume in
      Compose.

## 2. Email module
- [ ] `EMAIL_BACKEND` switch: `resend` (HTTP API) · `smtp` (aiosmtplib) · `console`
      (offline demo). Dry-run mode for tests.
- [ ] Conversation step: capture email, spell back for confirmation, store in case file.

## 3. Upload flow
- [ ] `send_image_upload_link(email)` tool: token row + templated email (link to the
      Vercel FE `/upload/{token}`).
- [ ] `web/app/upload/[token]` page (Next.js, mobile-friendly file input) + backend
      `POST /api/upload/{token}` (size/mime allowlist, expiry, single-use, EXIF-strip +
      resize — all enforced server-side).

## 4. Vision analysis                                  ⏸ review after this group
- [ ] `gpt-4o` vision call with JSON-schema response; prompt includes the case file.
- [ ] Merge analysis into `sessions.case_file`; set `image_uploads.status='analyzed'`.
- [ ] Unit tests with mocked OpenAI responses.

## 5. Agent wiring
- [ ] `check_image_analysis()` tool + prompt guidance (poll when the caller says they
      uploaded; fold `additional_steps` into troubleshooting).
- [ ] Follow-up email with findings when the session has already ended.

## 6. Gates
- [ ] pytest: token expiry / single-use / oversize / bad-mime rejections; analysis-merge.
- [ ] Extend `make transcript`: email capture spell-back scenario.
- [ ] `make lint` + `make test` clean.
- [ ] Tick roadmap Phase 3 `[x]` in `specs/constitution/roadmap.md`.
