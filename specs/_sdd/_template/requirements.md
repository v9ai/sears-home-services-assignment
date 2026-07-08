# <Feature> — Requirements

## Source
Roadmap phase "<name>" (specs/constitution/roadmap.md) — or — Pasted requirement (not from the roadmap):
> <verbatim user ask>

## Scope

### Included
- <exact behavior, fields, content shape — what ships>

### Not included (deferred)
- <explicitly out of scope, with a one-line why>

### Contract shapes
- Data / artifact shapes touched: <files, JSON fields, schema, served output>
- Source-of-truth file(s): `<path>` (section / line if relevant).
- Pipeline / build target: `<make ...>` (grounding · gate · build · deploy as applicable).

## Decisions
1. **<decision>** — <chosen option + rationale> (e.g. storage / model / data flow)
2. **<decision>** — <chosen option + rationale>
3. **Deploy path**: <command | no deploy> — <rationale>
4. **Gate path**: <which gate(s) prove this | none>

## Architecture impact
- Component / plane touched: <which part of the system this changes>
- Invariant-preserving (constitution unchanged) or constitution-revising (a non-negotiable
  in `mission.md` / `tech-stack.md` changes)?
- If constitution-revising: WHICH `mission.md` / `tech-stack.md` / `roadmap.md` bullet changes and how.

## Context
- Stack & conventions: cite `specs/constitution/tech-stack.md` + the real files this touches.
- Constraints: what must NOT change (memory pins, forbidden patterns, build requirements).
- Open questions / explicit deferrals: <bullets>
