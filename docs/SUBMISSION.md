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

## Local demo (no live number needed)

`docker compose up --build` from a fresh clone (see the root `README.md`
Quickstart) brings up the full backend (`:8000`), including the Tier-3 upload
page it serves at `/upload/{token}`. `make transcript` replays a scripted
diagnose → book conversation against the real agent without the phone channel;
the full walkthrough in `docs/demo-script.md` covers all three assignment tiers
over the live number.

## Secure credential sharing

No secrets are committed to this repository (`.env.example` is the contract;
mission non-negotiable 5). If the reviewer needs a working `OPENAI_API_KEY` or
other credential to exercise a hosted deployment rather than supplying their
own:

- Credentials are shared via a **time-limited secret link** (e.g. a password
  manager's one-time-secret share, such as 1Password's "Share Item" or
  Bitwarden Send) — never pasted into email, Slack, chat, screenshots, terminal
  transcripts, docs, or this repo.
- The link is sent to the reviewer's verified email address separately from
  this submission, and expires within 24–72 hours of the review window.
- Reviewers are otherwise encouraged to supply their own `OPENAI_API_KEY` in a
  local `.env` — the system needs no other paid account for the local demo.
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
