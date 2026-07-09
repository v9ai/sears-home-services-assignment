# Twilio CLI Debugging Toolkit — Requirements

## Source
User directive (2026-07-08):
> need a spec which can help debug twilio via cli

Dev-tooling feature supporting the telephony phase's pending, debug-heavy tail: wiring
the number's webhook to a live `PUBLIC_HOST` and passing the live-call checklist. A
failed call's evidence is spread across four surfaces — Twilio (webhook errors, call
status), the tunnel (ngrok), the app (structured phone-channel events — originally the
telephony bridge's `twilio.*` events from plan 5b, retired and re-sourced 2026-07-09 to
the Pipecat pipeline's `voice_*` / `twilio_ws_*` events per `2026-07-09-pipecat-voice-port`,
still correlated by `call_sid`/`session_id`), and the DB/recordings. This toolkit joins
them from one CLI.

Grounding already recorded in this repo: `twilio-cli 6.2.4` authenticated (profile
`vadim`) with its known quirk (`phone-numbers:buy:local` doesn't exist — raw
`api:core:*` commands do); number `+13186468479`, SID
`PN356e3d2a44afd34496997e66fb547da2`; ngrok Compose profile `phone`;
`app/phone/signature.py` (single signature implementation, reusable for offline
simulation).

## Scope

### Included
`scripts/twilio_debug.py` (subcommands below), `make phone-debug` passthrough, and a
**runbook table** (symptom → subcommand → raw twilio-cli equivalent) so a reviewer can
debug with the bare CLI even without the script.

| Subcommand | Does | Mutating? |
|---|---|---|
| `status` | One screen: number's current voice webhook URL/method (`twilio api:core:incoming-phone-numbers:fetch <PN…>`), live ngrok tunnel URL (local API `:4040/api/tunnels`), app `/healthz`, and a MISMATCH warning when webhook URL ≠ `{tunnel or PUBLIC_HOST}/twilio/voice` — the #1 misconfiguration | no |
| `wire [--yes]` | Resolve public URL (ngrok API, else `PUBLIC_HOST`) → `twilio api:core:incoming-phone-numbers:update <PN…> --voice-url …/twilio/voice --voice-method POST` → re-fetch + echo before/after. Dry-run without `--yes` | **yes (only one)** |
| `calls [--limit N]` | Recent calls: SID, status, duration, from (last-4) — `twilio api:core:calls:list` | no |
| `call <CallSid>` | Call detail (`api:core:calls:fetch`) + correlated app-side view: grep the phone-channel events by `call_sid` — the retained webhook events (`app/phone/webhook.py`) plus the Pipecat pipeline's `voice_*` / `twilio_ws_*` events and per-call metrics (`app/voice`, `2026-07-09-pipecat-voice-port`) — resolve `call_sid → session_id`, point at the `sessions` row and `RECORDINGS_DIR/{session_id}/` | no |
| `alerts` | `twilio api:monitor:alerts:list` filtered to errors — surfaces 11200 webhook-connection failures, TwiML errors, stream errors. THE answer to "the call never reached my server" | no |
| `simulate` | Fully offline vs Twilio: computes a valid `X-Twilio-Signature` (reusing `app/phone/signature.py` + `TWILIO_AUTH_TOKEN`), POSTs a synthetic inbound-call form to the local `/twilio/voice`, prints status + returned TwiML. Proves signature config, `PUBLIC_HOST` URL handling, and TwiML correctness with zero phone calls | no (local only) |
| `tail [--call-sid …]` | Follow app logs filtered to the phone-channel structured events — the retained webhook events plus the Pipecat `voice_*` / `twilio_ws_*` events and per-call metrics (`app/voice`) — optionally one call's stream. (Originally scoped to the telephony bridge's `twilio.*` events / plan 5b; that bridge is retired in `2026-07-09-pipecat-voice-port`, so the filter is re-sourced to the Pipecat trace vocabulary.) Degrades to plain grep of current log lines | no |
| `recordings [--call-sid …]` | Twilio-side recordings: `twilio api:core:recordings:list` (optionally filtered by call), metadata (duration/channels/source), and an authenticated media download to a local mp3 (`curl -u SID:TOKEN …/Recordings/<RE>.mp3`) — verified live 2026-07-08 | no |

### Follow-up candidate (recorded 2026-07-08)
- `simulate --media`: promote the proven scratchpad synthetic-caller script (OpenAI-TTS
  caller voice → μ-law Media Streams frames → full hosted loop; validated same day —
  see telephony validation.md) into a `twilio_debug` subcommand for repeatable
  phone-pipeline smoke without PSTN.

### Not included (deferred)
- Automated live two-way calls (Twilio test credentials cannot drive Media Streams) —
  the live-call checklist stays manual.
- Console UI automation, alert webhooks/paging, non-Twilio providers (forbidden anyway).

### Contract shapes
- Env: twilio-cli authenticates itself (profile); `simulate` needs
  `TWILIO_AUTH_TOKEN` (signing) + the local app URL; `NGROK_API_URL` (default
  `http://localhost:4040`).
- Runbook table lives in this spec and lands in the README via a declared
  deployment-deliverables delta.
- Gates: `make lint`, `make test` (offline units for signing + URL resolution +
  wire dry-run guard).

## Decisions
1. **Wrap twilio-cli, don't reimplement its REST client** — the CLI is already
   authenticated and recorded in the specs; the script shells out to it for all
   Twilio calls and uses HTTP only for ngrok's local API and the app's endpoints.
2. **Read-only by default; `wire` is the single mutating subcommand** — dry-run
   without `--yes`, and always echoes before/after webhook URLs.
3. **`simulate` reuses `app/phone/signature.py`** — one signature implementation in
   the repo; a passing simulate exercises exactly the code path a real Twilio POST
   hits (including the `PUBLIC_HOST` branch of `_webhook_url`).
4. **No secrets in output** — auth token/API keys never printed; phone numbers as
   last-4 (matches the observability redaction rules in telephony plan 5b).
5. **`call_sid` is the correlation key** across Twilio API ↔ app logs ↔ `sessions` ↔
   recordings. (Originally established by telephony plan 5b's `TwilioTraceContext`; that
   bridge is retired in `2026-07-09-pipecat-voice-port` — the same `call_sid`/`session_id`
   correlation is now carried by `app/obs.bind_call_context` across the retained webhook
   events and the Pipecat `voice_*` / `twilio_ws_*` events.)

## Architecture impact
- Invariant-preserving dev tooling: one script + one Make row; no runtime behavior
  change, no new services.

## Context
- Ownership: `scripts/twilio_debug.py` extends the telephony row (COORDINATION §3);
  `make phone-debug` row added to the Make table; README runbook section is a declared
  delta for deployment-deliverables.
- Constraints: never print secrets; `wire` only ever touches the recorded number SID.
- Open question (deferred): whether `tail` should read the JSON log stream from the
  Compose container (`docker compose logs -f app`) or a file — decide when plan 5b's
  log format lands.

## Runbook (symptom → command)

| Symptom | Toolkit | Raw twilio-cli equivalent |
|---|---|---|
| Call rings but nothing answers / dead air | `status` (webhook mismatch?) | `twilio api:core:incoming-phone-numbers:fetch PN356e3d2a44afd34496997e66fb547da2 --properties voiceUrl,voiceMethod` |
| "Application error" spoken by Twilio | `alerts` | `twilio api:monitor:alerts:list --limit 10` |
| Wired to a stale ngrok URL after restart | `wire --yes` | `twilio api:core:incoming-phone-numbers:update PN356e… --voice-url https://<tunnel>/twilio/voice --voice-method POST` |
| Is Twilio even receiving my calls? | `calls --limit 5` | `twilio api:core:calls:list --limit 5 --properties sid,status,duration,from` |
| Webhook 403s (signature) | `simulate` locally | n/a (local; check `TWILIO_AUTH_TOKEN` is the Account Auth Token — requirements Decision 6 of the telephony spec) |
| What happened during call X? | `call <CallSid>` then `tail --call-sid <CallSid>` | `twilio api:core:calls:fetch <CallSid>` + `docker compose logs app \| grep <CallSid>` |
| Where's the audio of call X? | `recordings --call-sid <CallSid>` | `twilio api:core:recordings:list -o json` (filter `callSid`), then `curl -u $TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Recordings/<RE>.mp3 -o call.mp3` |
