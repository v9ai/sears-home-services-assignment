# Submission — Sears Home Services AI Engineer Take-Home

## Repository

https://github.com/v9ai/sears-home-services-assignment

Branch/tag to review: `main` (integration branch; see
`specs/constitution/COORDINATION.md` for how six parallel feature branches merge
into it).

## Live phone number

**+1 (318) 646-8479** (Louisiana number, Twilio Programmable Voice + Media
Streams). The number is **always available** — its webhook points at the hosted
Cloudflare Worker deployment, so no local stack or tunnel needs to be running.
Wiring details: `specs/features/2026-07-08-telephony-twilio/` and the root
`README.md`.

For a **bookable test call**, use a seeded zip — Chicago `60601`/`60614`/`60642`
or Dallas `75201`/`75204`/`75225` (e.g. dishwasher @ 60601 → Marcus Bell, oven @
60614 → Priya Nair; full cell table in `docs/demo-script.md` §2). Any other zip
demonstrates the graceful no-coverage reply.

## Local demo (no live number needed)

`docker compose up --build` from a fresh clone (see the root `README.md`
Quickstart) brings up the full backend (`:8000`), including the Tier-3 upload
page it serves at `/upload/{token}`. Two things to know about the local surface:
the base compose runs **no interactive voice UI** (the live number above is the
interactive surface; `make transcript` replays a scripted diagnose → book
conversation against the real agent), and with the default
`EMAIL_BACKEND=console` the Tier-3 upload link is **printed to the app container
logs** rather than emailed. The full walkthrough in `docs/demo-script.md` covers
all three assignment tiers over the live number.

## Secure credential sharing

No secrets are committed to this repository (`.env.example` is the contract;
mission non-negotiable 5). If the reviewer needs a working `OPENAI_API_KEY` or
other credential to exercise a hosted deployment rather than supplying their
own:

- Credentials are shared via a **Bitwarden Send** time-limited secret link —
  never pasted into email, Slack, chat, screenshots, terminal transcripts, docs,
  or this repo. To request one, reply to the submission email; the link goes to
  your verified address and expires within 24–72 hours of the review window.
- Reviewers are otherwise encouraged to supply their own `OPENAI_API_KEY` in a
  local `.env` — the system needs no other paid account for the local demo.

What each review activity actually needs:

| Activity | Credentials |
|---|---|
| Call **+1 (318) 646-8479** | none (all secrets live server-side) |
| Read the repo | none (public) |
| `docker compose up --build` + `make transcript` + Tier-3 vision/console email | one `OPENAI_API_KEY` in `.env` |
| Judged eval lanes (`make eval`) | same key, with `EVAL_JUDGE_PROVIDER=openai` |
| Local phone stack (optional — the live number is hosted) | Twilio SID/token/number + ngrok, plus Deepgram + Cartesia keys, or `STT_PROVIDER=openai TTS_PROVIDER=openai` to stay one-key |
- Submission materials list credential **names** and setup steps only. They never
  contain API key values, auth tokens, database URLs with passwords, SMTP passwords, or
  `Authorization` / `Bearer` header values.

## Contact / availability window

- Contact: `nicolai.vadim@gmail.com`
- Availability for live testing / a walkthrough call: weekdays 9:00–18:00 ET,
  through Friday, July 24, 2026. Happy to coordinate a specific slot by email.

## What to look at first

1. Root `README.md` — quickstart, architecture, configuration.
2. `docs/technical-design.md` — the 1–2 page design doc (architecture, schema,
   tradeoffs, honestly-sequenced deferred work).
3. `docs/demo-script.md` — the 5-minute guided walkthrough.
4. `specs/` — the full spec-first paper trail (constitution → six feature
   triplets) this system was built from.
