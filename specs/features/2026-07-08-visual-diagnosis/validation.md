# Visual Diagnosis (Tier 3) — Validation

## Automated
- [ ] Token lifecycle tests: expired token rejected · token single-use · oversize file
      rejected · disallowed mime rejected.
- [ ] Mocked-vision merge test: analysis JSON lands in `case_file`, status transitions
      `pending → uploaded → analyzed`.
- [ ] Email module dry-run assertion (correct link, correct backend selection).
- [ ] `make lint` + `make test` clean; transcript email-capture scenario green.

## Manual
1. Full loop: give an email in-call → receive the link → upload a real appliance photo
   from a phone → back in the chat, say "I uploaded the photo" → the agent references a
   visible issue from the image and adjusts its troubleshooting.
2. Open an expired or already-used link → friendly error page, no upload accepted.
3. End the call before uploading → findings arrive by follow-up email.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Deferred scope (MMS, galleries, S3) recorded in the roadmap backlog.
- [ ] Roadmap Phase 3 ticked `[x]`.
