# The SDD Constitution — how this repo runs Spec-Driven Development

This is the **meta-constitution**: the agent-agnostic framework the specs in this repo
follow. This repo has **one family** — the whole application — whose three-doc
constitution lives at `specs/constitution/` and whose features live under
`specs/features/`. A *feature* is one unit of change, captured as a dated spec triplet.

---

## 1. The control-system principle

A spec is a **small, durable setpoint** that drives a **large, disposable output**. A few
sentences amplify into hundreds of lines of code, prose, or pipeline config; change one
sentence and the amplification regenerates. The spec — not the output — is the primary
artifact, because it has the highest leverage-to-size ratio, it survives across stateless
agent sessions, and it is the only place human architectural judgment is recorded once and
reused. The agent is a replaceable amplifier; the spec is the memory.

## 2. The three-doc constitution

`specs/constitution/` holds three durable, agent-agnostic documents:

- **`mission.md`** — the *why*: vision, audience, scope (in / out), and the
  **non-negotiables** that no feature may violate.
- **`tech-stack.md`** — the *common understanding*: runtime, frameworks, databases, the
  `make` commands that drive the work, forbidden patterns, and the models in use.
- **`roadmap.md`** — a *living, phased sequence* of features with `[ ]` / `[x]` checkboxes.

These are written **in conversation with the agent** and are the highest-priority,
lowest-trust-required instruction set for everything this repo generates.

## 3. The dated spec triplet

Every feature is a dated directory: `specs/features/YYYY-MM-DD-<slug>/` containing exactly
three files (copy `specs/_sdd/_template/`):

- **`requirements.md`** — *what* and *why*: source, scope (included / deferred), contract
  shapes, the key decisions, and context/constraints.
- **`plan.md`** — *how*: numbered task groups in dependency order, each with `[ ]`
  checkboxes and `[label]` tags marking which groups apply.
- **`validation.md`** — *proof*: the gates this surface triggers, manual checks, and the
  Definition of Done.

One feature = one dated dir. Naming is always `YYYY-MM-DD-<kebab-slug>`.

## 4. The 3-axis interview comes first

Before writing any spec file, run **one** structured interview across three fixed axes,
always in this order:

1. **SCOPE** — which surfaces / artifacts the change touches.
2. **DECISIONS** — the key technical and UX choices (model, storage, data flow, deploy path,
   which gate runs).
3. **CONTEXT** — constraints, an existing pattern to mirror, and what is explicitly deferred.

The interview is where the spec gets the precision the user expects; never skip it, even on
a one-line ask.

## 5. Gates are hard

Quality is enforced by **`make`-driven, pass/fail gates**, never by "looks right". Each
feature's `validation.md` names only the gates its surface actually triggers (build, lint,
tests, transcript gate, …). A gate that does not pass blocks the feature. Run gates
after each task group and pause for human review between groups — especially for areas where
small mistakes compound (migrations, booking logic).

## 6. The per-feature loop

`Specify → Clarify → Plan → Implement → Validate`, on a fresh agent context:

1. **Specify** — agent drafts the triplet from the constitution.
2. **Clarify** — close underspecified gaps *before* code; the spec becomes a reviewable
   artifact a human can disagree with while feedback is still cheap.
3. **Plan** — order task groups by risk; run risky groups (migrations, booking transactions)
   one at a time.
4. **Implement** — feature-by-feature, frequent commits, manageable diffs.
5. **Validate** — human-in-the-loop review against `validation.md`; a code mistake usually
   traces to a spec mistake, so fix **both** to keep intent and implementation in sync.

Between features, **replan** on a dedicated branch when a constitutional decision changes, so
git records which constitution version produced which output.

## 7. Definition of Done (repo-wide)

A feature is done only when every item holds:

- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All gates named in `validation.md` are green.
- [ ] If the change was constitution-revising, `mission.md` / `tech-stack.md`
      was updated alongside the code.
- [ ] Deferred scope is recorded as a roadmap follow-up.
- [ ] The matching `roadmap.md` phase is ticked `[x]`.

## 8. Agent replaceability

Specs are written against open standards, not a vendor. The `how` — which agent executes
the spec — is an interchangeable implementation detail; the durable artifact is the `what`
and the `why`.

---

## Authoring a spec

The ritual is always the same: **ground** (read this file + `specs/constitution/`) →
**interview** (the 3-axis interview) → **write the triplet** from
`specs/_sdd/_template/` → **stop for human review**. It produces **documents, not code**.

## When SDD is over-engineering

Match ceremony to the problem. Small or well-understood changes favor tight iterative loops;
heavyweight SDD pays for its overhead only on work that is **large *and* well-specified**. A
verbose spec that is more tedious to review than the code it describes is a failure, not a
win. This is why the deferred STT and telephony phases carry compact decision records in
`specs/constitution/roadmap.md` instead of full triplets — their triplets are authored when
the phases start.
