# Voice Diagnostic Core (Tier 1) — Validation

## Automated
- [ ] `make test` green: knowledge loader/schema, case-file merge, tool units,
      safety-interrupt unit.
- [ ] `make lint` clean.
- [ ] `make transcript` — scripted ~10-turn text conversation asserting:
      appliance identified by turn ≤ 3 · no question repeated for a fact already in the
      case file · "I smell gas" mid-flow triggers the safety interrupt script ·
      ≥ 2 troubleshooting steps delivered for a known symptom key.
- [ ] `make eval` — DeepEval conversational gate green: Knowledge Retention ≥ threshold
      (no fact re-asked), Role Adherence (persona), Conversation Completeness, G-Eval
      safety rubric (gas scenario scores as full interrupt).
- [ ] Compose smoke: fresh `docker compose up` → `/healthz` returns 200.

## Manual
1. Browser session: type "my washer is making a grinding noise and shows error E3" —
   confirm the agent identifies the appliance, collects onset/sound, delivers steps, and
   the TTS audio plays for every reply.
2. Say "I smell gas" mid-troubleshooting → interrupt fires (shutoff advice + offer to
   schedule), no further DIY steps.
3. Reload the tab mid-session → agent resumes without re-asking captured facts.
4. Case-file panel fills as facts are captured; subjective reply latency ≲ 3 s.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Deferred scope (STT, telephony, scheduling, vision) present in
      `specs/constitution/roadmap.md`.
- [ ] Roadmap Phase 1 ticked `[x]`.
