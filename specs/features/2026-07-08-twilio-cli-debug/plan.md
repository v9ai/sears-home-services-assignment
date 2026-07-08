# Twilio CLI Debugging Toolkit — Plan

Docs-first, then the script; every subcommand lands with its offline unit where one is
possible.

## 1. Runbook
- [x] Symptom → subcommand → raw twilio-cli table (in `requirements.md`) — useful
      before any code exists; raw column restricted to command forms verified against
      twilio-cli 6.2.4 (`api:core:*`, `api:monitor:*`).

## 2. Script skeleton + read-only subcommands
- [ ] `scripts/twilio_debug.py`: argparse subcommands; twilio-cli invoked via
      subprocess (JSON output `-o json`); ngrok tunnel discovery via
      `NGROK_API_URL/api/tunnels`; `status` mismatch detection; `calls`/`call`/
      `alerts` with last-4 number masking.
- [ ] `call <sid>`: log grep for `call_sid`, resolve `session_id`, print `sessions`
      row summary + recordings dir listing.

## 3. simulate + wire                                   ⏸ review after this group
- [ ] `simulate`: synthetic inbound-call form (CallSid/From/To), signature computed by
      importing `app/phone/signature.py`'s primitives, POST to local `/twilio/voice`,
      print status + TwiML. Exercises the `PUBLIC_HOST` `_webhook_url` branch.
- [ ] `wire`: dry-run default; `--yes` performs `api:core:incoming-phone-numbers:update`
      against the recorded PN SID only; echoes before/after voiceUrl.

## 4. tail correlation
- [ ] `tail [--call-sid]` over `docker compose logs -f app` (or a log file), filtered
      to `twilio.*` events — full fidelity once telephony plan 5b's structured events
      land; plain-grep fallback until then.

## 5. Plumbing
- [ ] `make phone-debug` passthrough target (`$(BIN)python scripts/twilio_debug.py $(cmd)`).
- [ ] README runbook section — declared as a deployment-deliverables delta (README is
      theirs); this triplet's runbook table is the source.

## 6. Gates
- [ ] pytest (offline, no Twilio API): simulate's signing round-trips through
      `app/phone/signature.validate_request`; ngrok-JSON→URL resolution unit; `wire`
      without `--yes` performs no update call (subprocess spy).
- [ ] `make lint` + `make test` clean.
- [ ] Manual: each subcommand run once against the live account (empty results are a
      pass — the command completing and rendering is the gate).

## Integration deltas (lead applies)
- `Makefile`: `phone-debug` row (Make table is shared).
- README: runbook section (owned by deployment-deliverables).
- `tech-stack.md` Make table + `COORDINATION.md` telephony ownership row — applied
  with this spec commit (constitution touch-points).
