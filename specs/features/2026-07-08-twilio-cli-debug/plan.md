# Twilio CLI Debugging Toolkit — Plan

Docs-first, then the script; every subcommand lands with its offline unit where one is
possible.

## 1. Runbook
- [x] Symptom → subcommand → raw twilio-cli table (in `requirements.md`) — useful
      before any code exists; raw column restricted to command forms verified against
      twilio-cli 6.2.4 (`api:core:*`, `api:monitor:*`).

## 2. Script skeleton + read-only subcommands
- [x] `scripts/twilio_debug.py`: argparse subcommands; twilio-cli invoked via
      subprocess (JSON output `-o json`); ngrok tunnel discovery via
      `NGROK_API_URL/api/tunnels`; `status` mismatch detection; `calls`/`call`/
      `alerts` with last-4 number masking. (Landed 2026-07-09; `recordings` included.)
- [x] `call <sid>`: log grep for `call_sid` (Compose app service), resolve
      `session_id`, print `sessions` row pointer + recordings dir listing.

## 3. simulate + wire
- [x] `simulate`: synthetic inbound-call form (CallSid/From/To), signature computed by
      importing `app/phone/signature.py`'s primitives, POST to local `/twilio/voice`,
      print status + TwiML. Exercises the `PUBLIC_HOST` `_webhook_url` branch.
- [x] `wire`: dry-run default; `--yes` performs `api:core:incoming-phone-numbers:update`
      against the recorded PN SID only; echoes before/after voiceUrl.

## 4. tail correlation
- [x] `tail [--call-sid]` over `docker compose logs -f app`, filtered to `twilio.*`
      events (plain-grep when `--call-sid` is given, so pre-5b log lines still match).

## 5. Plumbing
- [x] `make phone-debug` passthrough target (`$(BIN)python scripts/twilio_debug.py $(cmd)`).
- [x] README runbook section — "Debugging the phone channel (`make phone-debug`)"
      under Make commands; this triplet's runbook table is the source.

## 6. Gates
- [x] pytest (offline, no Twilio API): simulate's signing round-trips through
      `app/phone/signature.validate_request` (incl. the PUBLIC_HOST branch);
      ngrok-JSON→URL resolution unit; `wire` without `--yes` performs no update call
      (subprocess spy); output redaction (`tests/test_twilio_debug.py`, 10 tests).
- [x] `make lint` + `make test` clean.
- [x] Manual: read-only subcommands run once against the live account (2026-07-09):
      `status` (number fetched, webhook echoed, `/healthz` 200), `calls --limit 3`
      (3 real calls, from-numbers masked), `alerts` (empty = pass), `recordings`
      (3 dual-channel Twilio recordings listed), and `simulate` → 200 +
      `<Start><Recording/></Start><Connect><Stream>` TwiML against the running local
      app. **Owed**: `wire --yes` (deliberately not run — the live number's webhook
      currently points at a working tunnel; flipping it would break the live wiring)
      and the during-a-live-call correlation drill (validation.md Manual 4–5).

## Integration deltas (lead applies)
- `Makefile`: `phone-debug` row (Make table is shared). ✅
- README: runbook section (owned by deployment-deliverables). ✅
- `tech-stack.md` Make table + `COORDINATION.md` telephony ownership row — applied
  with this spec commit (constitution touch-points).
