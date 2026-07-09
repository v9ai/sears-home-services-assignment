# Twilio CLI Debugging Toolkit — Validation

## Automated (offline — no Twilio API in CI)
- [x] `simulate` signing unit: the signature the script computes is accepted by the
      app's own `app/phone/signature.validate_request` for the same URL+params
      (including the `PUBLIC_HOST`-differs-from-request-host case, where a
      local-URL signature is also asserted NOT to validate).
      (`tests/test_twilio_debug.py::test_simulate_*`)
- [x] ngrok resolution unit: fixture `api/tunnels` JSON → correct `https` public URL
      and derived `/twilio/voice` + `wss …/ws/twilio` forms.
      (`test_resolve_ngrok_url_*`, `test_derive_endpoints`)
- [x] `wire` guard: without `--yes`, no update subprocess is invoked (spy) and the
      dry-run output shows current vs proposed voiceUrl.
      (`test_wire_without_yes_never_updates`; `--yes` path covered by
      `test_wire_with_yes_updates_the_recorded_sid_only`)
- [x] Output redaction: no auth token, API-key-shaped string, or full phone number in
      any subcommand's rendered output (numbers as last-4) — every print goes through
      `redact()`. (`test_redact_scrubs_token_keys_and_numbers`,
      `test_calls_output_masks_numbers`)
- [x] `make lint` + `make test` clean (2026-07-09).

## Manual (against the live account/profile `vadim`)
1. [x] `status` — run 2026-07-09: shows the number (last-4), current voiceUrl
   (cloudflared quick tunnel), tunnel state (ngrok down), `/healthz` 200; the
   mismatch branch exercised (no public URL resolvable → explicit "cannot check"
   message; a stale-URL mismatch was separately reproduced during `simulate`, which
   403'd until signed against the app's actual `PUBLIC_HOST`).
2. [ ] `wire --yes` — **owed, deliberately**: the live number's webhook currently
   points at a working tunnel; flipping it to a resolvable public URL would break
   live calling. The dry-run path was run live; the update path is unit-covered.
3. [x] `simulate` — run 2026-07-09 against the running local app: 200 +
   `<Start><Recording channels="dual"/></Start><Connect><Stream url="wss://…/ws/twilio">`
   TwiML; the 403-on-wrong-PUBLIC_HOST case observed first (signature correctly
   rejected), proving the signature path end-to-end in both directions.
4. [~] `calls`/`recordings` verified live (3 real completed calls listed with masked
   from-numbers; 3 dual-channel Twilio recordings listed). The during-a-live-call
   `call <sid>` + `tail --call-sid` correlation drill remains owed (needs a handset).
5. [ ] Failure drill (dead webhook → `alerts` surfaces 11200 → `wire --yes` repairs)
   — owed with Manual 2 for the same reason.

## Definition of done
- [x] Each "Included" subcommand is observably true (offline gates + manual 1–3
      minimum; `wire --yes` mutation intentionally deferred, dry-run verified live).
- [x] Runbook table present here and delivered to the README (delta applied —
      "Debugging the phone channel" section).
- [x] No secrets in any output (automated redaction check + manual spot-check on the
      live runs: numbers rendered `…8479`-style, no token echoed).
- [x] Deferred scope (live-call automation, paging, console automation) recorded.
