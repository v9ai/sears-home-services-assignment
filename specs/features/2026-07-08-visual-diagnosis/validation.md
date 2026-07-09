# Visual Diagnosis (Tier 3) — Validation

## Automated
- [x] Token lifecycle tests: expired token rejected · token single-use · oversize file
      rejected · disallowed mime rejected. (`tests/test_visual_tokens.py`,
      `test_visual_upload_store.py`, `test_visual_upload_routes.py` — green in the
      full suite, 468 passed 2026-07-09.)
- [x] Mocked-vision merge test: analysis JSON lands in `case_file`, status transitions
      `pending → uploaded → analyzed`. (`tests/test_visual_pipeline.py`,
      `test_visual_vision_merge.py`, `test_visual_tools.py`.)
- [x] Email module dry-run assertion (correct link, correct backend selection).
      (`tests/test_visual_email.py` — extended 2026-07-09 with the Cloudflare Email
      Sending request-shape/bounce tests and `normalize_email` units after fixing the
      CF backend endpoint/payload and adding address normalization.)
- [x] `make lint` + `make test` clean; transcript email-capture scenario green
      (2026-07-09: lint clean, 468 tests passed, `visual_email_spellback` PASS in
      `make transcript`).
- [x] `make eval` green on the visual scenarios: captured email never re-asked
      (Knowledge Retention); G-Eval photo-findings rubric — post-upload guidance cites
      the vision analysis.
      Optional Tier 3 scenario set: `evals/scenarios/visual/*`. These gates are required
      only when claiming visual diagnosis as part of the submission.
      (2026-07-09: full judged `make eval` 33/33 GREEN on the DeepSeek judge, visual
      scenarios included.)

## Manual
1. Full loop: give an email in-call → receive the link → upload a real appliance photo
   from a phone → back in the chat, say "I uploaded the photo" → the agent references a
   visible issue from the image and adjusts its troubleshooting.
   *Partial evidence 2026-07-09*: a real GPT-4o Vision call through
   `app/vision/client.analyze_image` returned a correct `VisionAnalysis` (washer,
   water-pooling issue, matched symptoms, grounded steps); the full phone-to-upload
   loop with a handset remains a live-demo item.
2. Open an expired or already-used link → friendly error page, no upload accepted.
3. End the call before uploading → findings arrive by follow-up email.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Deferred scope (MMS, galleries, S3) recorded in the roadmap backlog.
- [x] Roadmap Phase 3 ticked `[x]` (2026-07-09).
