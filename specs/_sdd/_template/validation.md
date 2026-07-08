# <Feature> — Validation

## Automated (only the gates this feature's surface triggers)
- [ ] <test / eval gate — `make <...>` clean, hard pass/fail>              [logic changed]
- [ ] <parity / consistency check green>                                   [gate rule changed]
- [ ] `make lint` + `make test` clean.                                     [code changed]

## Manual
1. <human read / playback / inspection of the changed artifact>
2. <after deploy: exercise the running surface, confirm the change works without errors>
3. <spot-check that derived artifacts match their source>

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] If constitution-revising: `mission.md` / `tech-stack.md` updated alongside the change.
- [ ] Deferred scope recorded as a follow-up bullet in `specs/constitution/roadmap.md`.
- [ ] Matching roadmap phase ticked `[x]`.
