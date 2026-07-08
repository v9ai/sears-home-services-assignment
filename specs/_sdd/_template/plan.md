# <Feature> — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups. Delete the `[label]` groups that don't apply to this feature.

## 1. Source of truth                                  [content / data change]
- [ ] Edit the authoritative file(s) named in `requirements.md` `### Contract shapes`.
- [ ] If generated/derived output must be rebuilt, run the regeneration target
      (`make <...>`) rather than hand-editing the derived file.

## 2. Propagation                                      [if derived artifacts exist]
- [ ] Mirror the source edit into every derived artifact that must stay in sync (JSON
      dumps, served files, caches). Keep them byte-consistent; never hand-edit one side.

## 3. Pipeline / logic change                          [if pipeline change]
- [ ] Edit the relevant module; run via `make` per `tech-stack.md` (no raw tooling the
      constitution forbids).
- [ ] If a gate rule changed, keep any parity oracle in lockstep and re-verify it.

## 4. UI / component                                   [if UI change]
- [ ] Edit the page/component following the repo's styling convention (e.g. no agent/LLM
      logic in the frontend).

## 5. Gates
- [ ] <the test / eval / build gate this surface triggers — `make <...>`, hard pass/fail>
- [ ] `make lint` + `make test` clean.

## 6. Deploy                                           [if deploy in scope]
- [ ] <deploy command from `tech-stack.md`>.
- [ ] Verify the running surface responds and renders the change.
- [ ] Tick the matching roadmap phase `[x]` in `specs/constitution/roadmap.md`.
