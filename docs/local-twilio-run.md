# Running the app locally against real Twilio

How to place a **real phone call** to the provisioned Twilio number `+13186468479`
and have it hit the **local** Docker stack (not the Cloudflare deployment),
exercising the full telephony path: `/twilio/voice` webhook → TwiML →
`wss://.../ws/twilio` Media Streams bridge → STT → agent → streaming TTS.

> This is a **local-dev runbook**. The canonical hosted path is the Cloudflare
> deploy (`sears-home-services-app.eeeew.workers.dev`); see
> `docs/twilio-webhook-setup.md` for the production wiring.

---

## Call flow

```
caller (phone)
   └─► Twilio  ──POST──►  https://<tunnel-host>/twilio/voice      (signed; TwiML returned)
              ──WSS───►  wss://<tunnel-host>/ws/twilio            (μ-law media frames)
                              │
                     cloudflared quick tunnel
                              │
                     http://localhost:8000  ──►  FastAPI app container  ──►  Postgres (:5433)
```

The local app is not publicly reachable, so Twilio can't call it directly. A
**cloudflared quick tunnel** gives `localhost:8000` a public `https`/`wss` host,
and we temporarily repoint the Twilio number's voice webhook at that host.

## Why `PUBLIC_HOST` must match the tunnel exactly

The app reads `PUBLIC_HOST` at request time to:

- **rebuild the exact URL for `X-Twilio-Signature` validation** —
  `app/phone/webhook.py::_webhook_url`
- **emit `wss://{PUBLIC_HOST}/ws/twilio` in the TwiML** —
  `app/phone/twiml.py::build_stream_response`

Signature validation (`app/phone/signature.py`, keyed on `TWILIO_AUTH_TOKEN`)
recomputes the signature over the URL Twilio signed. If `PUBLIC_HOST` and the
Twilio number's `voice_url` don't match **byte-for-byte** (scheme + host +
path), every request `403`s.

---

## Prerequisites

- Docker running; the local stack builds via `make up` / `docker compose up --build`.
- `.env` populated with Twilio creds: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
  (the **Account Auth Token**, not an API key), `TWILIO_PHONE_NUMBER=+13186468479`.
- `cloudflared` (`brew install cloudflared`) and, for repointing the number, the
  Twilio CLI (`brew install twilio/brew/twilio-cli`) — or use the REST API (below).

---

## Runbook

### 1. Start the tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

Note the printed `https://<random>.trycloudflare.com` host. **Keep this process
running** — it is the public front door for `localhost:8000`. WSS is forwarded
too, so `/ws/twilio` works.

> ⚠️ Quick-tunnel hosts are **random per launch**. Every restart of `cloudflared`
> means redoing steps 2–3 with the new host.

### 2. Point the local app at the tunnel host (via `env.local`)

Local overrides live in **`env.local`** (gitignored), merged in by a gitignored
**`docker-compose.override.yml`** — so `.env` stays at its canonical
Cloudflare value and nothing tracked changes.

`env.local`:
```dotenv
# Bare host, no scheme, no trailing slash.
PUBLIC_HOST=<random>.trycloudflare.com
```

`docker-compose.override.yml` (auto-merged by compose; later `env_file` wins):
```yaml
services:
  app:
    env_file:
      - .env
      - env.local
```

Keep the override out of git without editing the tracked `.gitignore`:
```bash
echo 'docker-compose.override.yml' >> .git/info/exclude
# env.local is already covered by .gitignore
```

Recreate the app so it re-reads the merged env, then confirm reachability:
```bash
docker compose up -d --force-recreate app
docker compose config | grep PUBLIC_HOST            # should show the tunnel host
curl -s https://<random>.trycloudflare.com/healthz  # {"status":"ok"}
```

### 3. Repoint the Twilio number's voice webhook

**Twilio CLI:**
```bash
twilio phone-numbers:update +13186468479 \
  --voice-url "https://<random>.trycloudflare.com/twilio/voice" --voice-method POST
```

**REST API (creds from `.env`):**
```bash
export $(grep -E '^TWILIO_(ACCOUNT_SID|AUTH_TOKEN)=' .env | xargs)
SID=$(curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers.json?PhoneNumber=%2B13186468479" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['incoming_phone_numbers'][0]['sid'])")
curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers/$SID.json" \
  --data-urlencode "VoiceUrl=https://<random>.trycloudflare.com/twilio/voice" \
  --data-urlencode "VoiceMethod=POST"
```

### 4. Place the call & watch logs

```bash
docker compose logs -f app
```

Dial **+13186468479**. Expected sequence:
`POST /twilio/voice` → 200 + `<Connect><Stream>` TwiML → `WebSocket /ws/twilio
[accepted]` → `start` → `media` frames → STT turn → streamed TTS back → `stop`.

---

## Offline webhook proof (no real call)

Verifies signature validation + TwiML generation without dialing. Signs a
synthetic inbound-call POST with the real `TWILIO_AUTH_TOKEN` against the
`PUBLIC_HOST`-derived URL, then POSTs to the local app:

```bash
docker compose exec -T app python - <<'PY'
import os, urllib.request, urllib.parse
from twilio.request_validator import RequestValidator
token = os.environ["TWILIO_AUTH_TOKEN"]; host = os.environ["PUBLIC_HOST"]
url = f"https://{host}/twilio/voice"
params = {"CallSid":"CAtest0000000000000000000000000001",
          "AccountSid":os.environ["TWILIO_ACCOUNT_SID"],
          "From":"+15005550006","To":os.environ["TWILIO_PHONE_NUMBER"],
          "CallStatus":"ringing","Direction":"inbound"}
sig = RequestValidator(token).compute_signature(url, params)
req = urllib.request.Request("http://localhost:8000/twilio/voice",
        data=urllib.parse.urlencode(params).encode(),
        headers={"X-Twilio-Signature":sig,
                 "Content-Type":"application/x-www-form-urlencoded"})
r = urllib.request.urlopen(req, timeout=10)
print("HTTP", r.status); print(r.read().decode())
PY
```

Expect `HTTP 200` and TwiML whose `<Stream url="wss://<tunnel-host>/ws/twilio">`
matches the current tunnel, with `<Start><Recording recordingChannels="dual"/>`
when recording is enabled.

---

## Issues hit during first live call — and fixes

The first real call connected at the transport layer (`POST /twilio/voice` 200,
`/ws/twilio` accepted) but broke mid-turn. Both root causes were the **same
stale container image** — `docker compose up --force-recreate` reuses the
existing image; it does **not** rebuild. The image predated recent commits.

| Symptom in logs | Root cause | Fix |
|---|---|---|
| `TypeError: RealAgent.handle_turn() got an unexpected keyword argument 'trace'` (`app/phone/bridge.py:119` → `real_agent.py`) — kills the WS turn | Image built before commit `8508823` ("Fix … RealAgent/bridge trace-kwarg TypeError"); `bridge.py` passes `trace=` but the baked `real_agent.py::handle_turn` had no `trace` param | **Rebuild** the image so it includes the committed fix |
| `PermissionError: [Errno 13] Permission denied: 'data/tts_cache'` and `data/recordings/<session>` (`tts_cache_write_failed`, `recording_write_failed`) — non-fatal but recordings/TTS-cache don't persist | Image predated `Dockerfile` lines 52–53 (`mkdir -p data/... && chown -R appuser:appuser data`); container `data/` was `root`-owned and `data/tts_cache` didn't exist. The `recordings`/`uploads` **named volumes** were also initialized `root`-owned and persist across rebuilds | **Rebuild** creates `data/tts_cache` correctly; then **chown the pre-existing named volumes** in place |

Commands:
```bash
# 1. Rebuild (picks up committed code + Dockerfile data-dir setup)
docker compose up -d --build app

# 2. Fix ownership of the pre-existing named volumes (recordings, uploads)
#    which a rebuild alone does NOT re-initialize
docker compose exec -u root app chown -R appuser:appuser /app/data
```

**Rule of thumb:** after pulling code changes, use `docker compose up -d --build`
(not just `--force-recreate`) or `make up`, so the image reflects the source.

### Verify the fixes

```bash
# handle_turn now accepts `trace`
docker compose exec -T app sed -n '117,125p' app/phone/real_agent.py

# data dirs owned by appuser and writable
docker compose exec -T app sh -c 'id -un; ls -ld data data/recordings data/tts_cache data/uploads'
```

### Stuttering during the reply (barge-in echo loop)

**Symptom:** heavy stuttering; `twilio.call.summary` showed `barge_ins=8` over 12
turns in 80 s, with barge-ins firing milliseconds apart *within a single reply*.

**Root cause:** barge-in was triggered per-frame by a single 20 ms frame clearing
the low turn-segmentation RMS threshold (500), with no debounce and no echo
tolerance (`app/phone/routes.py` + `app/phone/vad.py::frame_is_speech`). A real
PSTN call has **no acoustic echo cancellation**, so the agent's own TTS returns on
the inbound leg while it speaks → trips the threshold → `interrupt_playback()`
flushes the reply and sends Twilio `clear` → the still-streaming agent restarts the
next chunk → trips again. The reply is chopped into fragments = stuttering.

**Fix:** `app/phone/vad.py` gained `BargeInDetector` — barge-in now requires a run
of **consecutive** inbound frames (`VAD_BARGEIN_FRAMES`, default 4 ≈ 80 ms) clearing
a **higher** threshold than segmentation (`VAD_BARGEIN_THRESHOLD`, default 2000 vs.
500), since near-end speech is louder than returned echo. `app/phone/routes.py`
uses it only while `bridge.is_playing` and resets the run otherwise. Both knobs are
env-tunable: raise `VAD_BARGEIN_THRESHOLD` / `VAD_BARGEIN_FRAMES` if echo still
trips it, lower them if genuine interruptions feel unresponsive.

```bash
docker compose up -d --build app   # rebuild after the code change
# then confirm on the next call: barge_ins should be ~0 unless you actually talk over the agent
docker compose logs app --since 5m | grep 'twilio.call.summary'
```

### Agent replying to phantom turns (echo → STT hallucinations)

**Symptom:** after the barge-in fix, a call showed 0 barge-ins but the agent kept
answering junk. STT transcripts were `watch.` / `Wow.` / `谢谢。` / `sushi.` /
`好奇。` from a Romanian (`+40`) caller — classic Whisper-family hallucinations on
short, near-silent clips.

**Root cause (same echo, different path):** the turn segmenter ran *unconditionally*
— it buffered the agent's own TTS echo during playback and, ~300 ms after each reply,
emitted it as a ~0.5 s phantom "caller turn." `gpt-4o-transcribe` was called with no
language hint, so those echo/noise clips became random words (and Chinese).

**Fix (two layers):**

1. **Half-duplex gating** (`app/phone/routes.py`): while `bridge.is_playing`, inbound
   frames go *only* to the `BargeInDetector` — they are **not** fed to the segmenter,
   so echo can't become a turn. A genuine barge-in resumes segmentation from that
   frame on.
2. **Turn-quality + language guards:**
   - `TurnSegmenter` now drops turns with less than `VAD_MIN_SPEECH_MS` of real speech
     (`app/phone/vad.py`). Default in code is **0 (off)** to preserve unit-test
     behavior; the live deployment sets `VAD_MIN_SPEECH_MS=300` in `env.local`.
   - `OpenAITranscriber` sends a `language` hint (`app/phone/stt.py`), defaulting to
     `en` and overridable via `OPENAI_STT_LANGUAGE` (set `""` for auto-detect).

`env.local` carries the live tuning:
```dotenv
VAD_BARGEIN_THRESHOLD=2000
VAD_BARGEIN_FRAMES=4
VAD_MIN_SPEECH_MS=300
OPENAI_STT_LANGUAGE=en
```

Verify on the next call — `phone_turn_stt_done` should only log real utterances,
and the agent should stop answering things nobody said:
```bash
docker compose logs app --since 5m | grep -E 'phone_turn_stt_done|twilio.call.summary'
```

---

## Verification checklist

- [ ] `curl https://<tunnel>/healthz` → `{"status":"ok"}` (public reachability)
- [ ] Offline signed POST → `HTTP 200` + `<Connect><Stream>` TwiML at the tunnel host
- [ ] Live call: `POST /twilio/voice` 200 → `/ws/twilio [accepted]` → `media` frames
- [ ] No `TypeError`/`handle_turn` in logs during the turn
- [ ] No `PermissionError` on `data/tts_cache` or `data/recordings`
- [ ] Agent audio audible on the call; recording persists under `data/recordings/<session>`

---

## Teardown / revert

```bash
# 1. Point the number back at the Cloudflare deploy
twilio phone-numbers:update +13186468479 \
  --voice-url "https://sears-home-services-app.eeeew.workers.dev/twilio/voice" --voice-method POST

# 2. Drop local overrides
rm env.local docker-compose.override.yml
#   (optional) remove the git exclude line for docker-compose.override.yml

# 3. Back to .env's canonical host
docker compose up -d --force-recreate app

# 4. Stop the cloudflared tunnel process (Ctrl-C)
```

---

## Caveats

- **Ephemeral tunnel host** — `trycloudflare.com` hosts change on every
  `cloudflared` restart. Re-do steps 2–3 with the new host each time.
- **`web` frontend not required** for the phone channel; start it with
  `docker compose up -d web` only for the recordings-replay UI (`:3000`).
- **Secrets** — `TWILIO_AUTH_TOKEN` / `NGROK_AUTHTOKEN` are backend-only; never
  expose to `web`/client JS/logs (`specs/constitution/tech-stack.md`).
- `.env`, `env.local`, `env.local`-style files, and `docker-compose.override.yml`
  are all kept out of git (`.gitignore` + `.git/info/exclude`).
