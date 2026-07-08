# Twilio Console — Voice Webhook Setup

How to point the live Twilio number at this app's inbound-call webhook. Do this once a
public HTTPS host exists (a Cloudflare Containers deploy, or an `ngrok` tunnel for local
dev). Nothing here requires editing code — it is pure Twilio-side configuration.

## The number

| Field | Value |
| --- | --- |
| Phone number | `+1 (318) 646-8479` (E.164: `+13186468479`) |
| Number SID | `PN356e3d2a44afd34496997e66fb547da2` |
| Region | Louisiana, US |
| twilio-cli profile | `vadim` |

## What to configure

The app answers inbound calls at **`POST {PUBLIC_HOST}/twilio/voice`**. That endpoint
validates Twilio's `X-Twilio-Signature` and returns TwiML
(`<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio"/></Connect>`) that opens the Media
Streams WebSocket. **You only configure the `/twilio/voice` URL** — the `wss://…/ws/twilio`
stream URL is emitted by the returned TwiML at call time, *not* a console field.

`{PUBLIC_HOST}` is the public host of the running backend, e.g.
`https://sears-hvac.example.workers.dev` or `https://<subdomain>.ngrok.app`. It must be
HTTPS and publicly reachable by Twilio.

### Native call recording

The TwiML also opens `<Start><Recording recordingChannels="dual"/></Start>` before the
`<Connect>` (`app/phone/twiml.py`) — `<Start>` verbs run asynchronously, so Twilio
records the whole call in parallel with the Media Stream without blocking it. This is
what makes a call show up in Twilio's own **Recordings** resource
(console.twilio.com → Monitor → Logs → Call Recordings), independent of the app's own
per-turn WAV/MP3 capture (`app/recordings/routes.py`).

- Toggle: `TWILIO_CALL_RECORDING_ENABLED` (default on; set to `0`/`false` to disable).
- Correlation: the session's `sessions.call_sid` column (added by migration
  `0005_call_sid`) is set from the Media Stream `start` event's `CallSid` in
  `PhoneCallRuntime.start_session` (`app/phone/real_agent.py`).
- Lookup: `GET /api/recordings/{id}` does a **live** REST call
  (`client.recordings.list(call_sid=...)`, `app/phone/twilio_client.py`) — no separate
  metadata table or recording-status webhook. Playback goes through
  `GET /api/recordings/{id}/twilio-audio/{recording_sid}`, which proxies Twilio's media
  URL with HTTP Basic Auth server-side (the Auth Token can never reach the browser).
  Shown in the web app's `/recordings/{id}` detail page as a "Twilio call recording" card.

### Console path

Twilio Console → **Phone Numbers → Manage → Active numbers** → click **(318) 646-8479** →
**Voice Configuration** section:

| Console field | Value |
| --- | --- |
| **Configure with** | Webhook, TwiML Bin, Function, Studio Flow → **Webhook** |
| **A call comes in** | `{PUBLIC_HOST}/twilio/voice` (exact, no trailing slash) |
| **A call comes in → HTTP method** | **HTTP POST** |
| **Primary handler fails** (optional) | leave blank, or a status page URL |
| **Call status changes** (optional) | leave blank — not used this phase |

Concrete example once `PUBLIC_HOST=sears-hvac.example.workers.dev`:

```
A call comes in:  https://sears-hvac.example.workers.dev/twilio/voice   [HTTP POST]
```

Click **Save configuration**. Messaging/SMS config is out of scope (deferred to backlog).

> The webhook URL you set here **must byte-for-byte match** what the app signs against.
> The app derives that URL from the `PUBLIC_HOST` env var (see
> `app/phone/webhook.py::_webhook_url`); if `PUBLIC_HOST` and the console URL disagree on
> scheme/host/trailing-slash, every request fails signature validation with **403**.

### CLI alternative (equivalent to the console steps)

```bash
# Requires TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN in the environment (never echo them).
twilio api:core:incoming-phone-numbers:update \
  PN356e3d2a44afd34496997e66fb547da2 \
  --voice-url="https://<PUBLIC_HOST>/twilio/voice" \
  --voice-method=POST
```

### Local dev via ngrok

```bash
ngrok http 8000                       # tunnels the local FastAPI backend
# → set PUBLIC_HOST to the printed https host (bare, no scheme, in .env), e.g.
#   PUBLIC_HOST=abc123.ngrok.app
# → set the console "A call comes in" URL to https://abc123.ngrok.app/twilio/voice (POST)
```

The Compose `phone` profile (`make up`) runs ngrok alongside the backend for this.

## Required credentials / env (secrets stay in `.env` only — never commit or print)

| Var | Purpose | Status (this session) |
| --- | --- | --- |
| `TWILIO_ACCOUNT_SID` | Twilio account id; needed for CLI/REST webhook update + live call + Recordings API lookups | **EMPTY** |
| `TWILIO_AUTH_TOKEN` | **Account Auth Token** (Console → Account Info), keys `X-Twilio-Signature` validation and Recordings API/media auth. NOT an API Key secret. | **EMPTY** |
| `TWILIO_PHONE_NUMBER` | The E.164 number above | SET |
| `PUBLIC_HOST` | Public HTTPS host serving the webhook + WSS bridge | **EMPTY** |
| `NGROK_AUTHTOKEN` | Only for the local-dev `phone` Compose profile | EMPTY |

## Manual live-call checklist — BLOCKED

**Cannot be executed in this session.** A real inbound call requires all three of:
`TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, and a live `PUBLIC_HOST` — all currently empty.
Until they are set (and the console webhook saved per above), the checklist below is
un-runnable; do not mark it passed.

To unblock:
1. Put the real `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` (Account Auth Token) in `.env`.
2. Stand up a public host (Cloudflare deploy or `ngrok http 8000`) and set `PUBLIC_HOST`.
3. Point the number's **A call comes in** webhook at `{PUBLIC_HOST}/twilio/voice` (POST).
4. Restart the backend so it reads the new env, then run:

- [ ] Call `+1 (318) 646-8479` → spoken greeting within ~2 s of answer.
      *(On a trial Twilio account, Twilio plays its own disclaimer first — expected, not
      a failure. See requirements.md trial-account caveat.)*
- [ ] "my refrigerator stopped cooling yesterday" → appliance + symptom captured;
      troubleshooting steps spoken back.
- [ ] Interrupt mid-sentence → playback stops (barge-in), agent yields the turn.
- [ ] "I smell gas" → safety-interrupt script, no further DIY steps.
- [ ] Book by voice: zip → offered slots → read-back → "yes" → spoken confirmation;
      `appointments` row present, slot `booked`.
- [ ] Continue the call → agent does not re-ask zip / appliance / chosen slot.
- [ ] Per-turn latency logs within budget (p50 ≤ 2.5 s to first audio).

## Trace / log runbook

The phone path must be debuggable from container logs alone. For every live-call
checklist run, save the `call_sid` from Twilio Console and the `session_id` from app
logs, then verify one complete trace.

### Find one call

```bash
# Local Compose
docker compose logs app | rg 'call_sid=CA|session_id='

# Cloudflare
npx wrangler tail --config wrangler.app.toml | rg 'call_sid=CA|session_id='
```

Once the `call_sid` or `session_id` is known:

```bash
docker compose logs app | rg 'call_sid=<CALL_SID>|session_id=<SESSION_ID>'
```

### Required ordered events

The trace must show these events in order:

1. `twilio.webhook.received` → `twilio.webhook.accepted`
2. `twilio.stream.accepted` → `twilio.stream.start`
3. `twilio.session.created`
4. `twilio.greeting.started` → `twilio.greeting.completed`
5. Per turn: `twilio.vad.speech_started` → `twilio.vad.speech_ended` →
   `twilio.stt.started` → `twilio.stt.completed` → `twilio.agent.turn_started` →
   optional `twilio.agent.tool_invoked` → `twilio.tts.started` →
   `twilio.audio.first_frame_sent` → `twilio.agent.turn_completed`
6. If barge-in is tested: `twilio.barge_in.clear_sent`
7. `twilio.stream.stop` or `twilio.stream.disconnect`
8. `twilio.call.summary`

### Required fields

Every event should include `event`, `component`, `provider=twilio`, `channel=phone`,
and all known correlation fields: `session_id`, `call_sid`, `stream_sid`, `turn_index`.
Phone numbers must appear only as `from_hash` / `to_hash` and optional last-four
fields. The summary must include inbound/outbound frame counts, turn count, barge-in
count, recording counts, final status, and p50/p95 first-audio latency.

Per-turn latency logs must include:

- `eos_to_stt_ms`
- `stt_to_agent_first_token_ms`
- `agent_first_token_to_first_audio_ms`
- `eos_to_first_audio_ms`
- `turn_total_ms`

### Redaction audit

Before marking the live-call checklist passed, grep the captured logs and confirm none
of these appear: raw phone numbers, `X-Twilio-Signature`, `TWILIO_AUTH_TOKEN`,
OpenAI/DeepSeek keys, database URLs, media payloads, transcript text, upload links,
email addresses, or full request bodies.

Failure logs must use typed events such as `invalid_signature`, `missing_config`,
`caller_hangup`, `twilio_disconnect`, `malformed_frame`, `stt_failed`,
`agent_failed`, `tts_failed`, `db_persist_failed`, `recording_write_failed`, or
`unexpected_exception`.
