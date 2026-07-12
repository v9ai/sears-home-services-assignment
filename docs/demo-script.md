# Demo Script — 5-Minute Reviewer Walkthrough

A guided path through all three assignment tiers: diagnose → book → photo.
The demo is voice-first: **call the live number** (step 4 has the number; it is
the primary channel). For a keyless local run, `make up` then `make transcript`
replays a scripted end-to-end conversation against the real agent.

Each step below is annotated with what to look for and which non-negotiable or
requirement it demonstrates. Steps 1-3 describe the conversation on a live call.

## 1. Diagnose (Tier 1) — ~90 s

1. Call the number. The agent greets you and asks what's going on.
2. Say: `My washer is making a loud banging noise during the spin cycle.`
   - **Look for**: the agent identifies the appliance (washer) and records the
     symptom into its case file without asking you to repeat it later.
3. Answer its follow-up questions (when it started, any error code, etc.) as asked.
   - **Look for**: it never re-asks something you already said — mission
     non-negotiable 2.
4. It gives troubleshooting steps from the curated knowledge base, spoken one
   step at a time.
5. **Safety interrupt check**: start a fresh conversation and mention
   `I smell gas near the oven.` The agent must halt troubleshooting immediately,
   advise shutoff + professional help, and offer to schedule a technician — no
   flow may route around this (mission non-negotiable 1).

## 2. Book a technician (Tier 2) — ~90 s

1. Continuing from step 1 (or after declining to keep troubleshooting), say
   `Can you send someone out?`
2. Give a zip code when asked (the agent also asks what days or times work best —
   any answer or "no preference" works).
   - **Look for**: if you already mentioned your zip earlier in the conversation,
     it is not asked again.
   - **Use a covered zip.** Seeded coverage is Chicago (60601, 60614, 60642) and
     Dallas (75201, 75204, 75225). Known-good cells: **dishwasher or refrigerator
     @ 60601** (Marcus Bell), **washer @ 60601** (Ava Chen / Diego Ruiz), **oven or
     HVAC @ 60614** (Priya Nair), **dryer @ 75201** (Jordan Lee / Nina Osei). Any
     other zip demonstrates the graceful no-coverage reply instead — real, but a
     shorter demo.
3. The agent offers up to 3 available slots matched by zip + appliance specialty.
4. Pick one — accepting a specific slot **is** the confirmation. The agent **reads
   back** technician name + date + time as it books (mission non-negotiable 4) and
   confirms with an appointment id.
   - **Look for**: try booking the same slot again from a second session — the
     atomic claim means the second attempt gets `slot_taken`, not a double-booked
     appointment.

## 3. Photo upload (Tier 3) — ~90 s

1. During or after diagnosis, say `I have a photo of the issue.`
2. The agent asks for (or confirms) your email, spells it back for confirmation,
   and sends an upload link. In local dev with `EMAIL_BACKEND=console` (the
   default), the link is printed to the `app` container logs — `docker compose
   logs app` — instead of a real inbox.
3. Open the printed `{APP_BASE_URL}/upload/{token}` link — a minimal page the
   backend serves itself — and upload a photo of an appliance (jpeg/png/webp,
   ≤ 10 MB).
4. Back on the call, say `I just uploaded the photo.`
   - **Look for**: the agent calls `check_image_analysis` and incorporates GPT-4
     Vision's findings into its spoken guidance.

## 4. Live phone number (the primary review surface)

Call **+1 (318) 646-8479**. The same greeting, diagnosis, booking, and safety
interrupt behavior apply over the phone — it's the same tool set and case-file
memory behind a Twilio Media Streams adapter (Pipecat pipeline on the hosted
Cloudflare Worker), not a different implementation. Use the covered zips from
step 2 above for a bookable call. See
`specs/features/2026-07-08-telephony-twilio/` for the wiring details.

## Wrap-up talking points

- One agent, two transports (`/ws/call` for text/TTS, `/ws/twilio` for the phone),
  sharing the same tool set and case-file memory — see `docs/technical-design.md`.
- Everything above ran from `docker compose up` on a fresh clone; no cloud account
  required for steps 1–3.
