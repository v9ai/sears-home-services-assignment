# Twilio CLI Debugging Toolkit — Validation

## Automated (offline — no Twilio API in CI)
- [ ] `simulate` signing unit: the signature the script computes is accepted by the
      app's own `app/phone/signature.validate_request` for the same URL+params
      (including the `PUBLIC_HOST`-differs-from-request-host case).
- [ ] ngrok resolution unit: fixture `api/tunnels` JSON → correct `https` public URL
      and derived `/twilio/voice` + `wss …/ws/twilio` forms.
- [ ] `wire` guard: without `--yes`, no update subprocess is invoked (spy) and the
      dry-run output shows current vs proposed voiceUrl.
- [ ] Output redaction: no auth token, API-key-shaped string, or full phone number in
      any subcommand's rendered output (numbers as last-4).
- [ ] `make lint` + `make test` clean.

## Manual (against the live account/profile `vadim`)
1. `status` — shows the number's current voiceUrl, tunnel state, `/healthz`, and
   correctly flags a mismatch when the webhook points elsewhere.
2. `wire --yes` — flips the live number's voice webhook to the current tunnel;
   `status` immediately confirms; before/after echoed.
3. `simulate` — local POST returns 200 + `<Connect><Stream>` TwiML.
4. During one live call: `calls` lists it; `call <sid>` joins Twilio detail with the
   app-side `session_id` + recordings dir; `tail --call-sid <sid>` streams the ordered
   `twilio.*` events (post-5b).
5. Failure drill: point the webhook at a dead URL, call once, `alerts` surfaces the
   11200-class error, `wire --yes` repairs it.

## Definition of done
- [ ] Each "Included" subcommand is observably true (offline gates + manual 1–3
      minimum; 4–5 with the live checklist).
- [ ] Runbook table present here and delivered to the README (delta applied).
- [ ] No secrets in any output (automated redaction check + manual spot-check).
- [ ] Deferred scope (live-call automation, paging, console automation) recorded.
