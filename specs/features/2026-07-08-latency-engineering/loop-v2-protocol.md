# Latency Loop v2 Protocol — canonical committed copy

> Runnable copy: `.claude/skills/latency-maximize/SKILL.md` (machine-local, gitignored).
> This committed copy is the source of truth on any drift. Invoke via
> `/latency-maximize` (one iteration) or `/loop /latency-maximize` (self-paced).


# Latency Maximize — one loop-v2 iteration

You are executing ONE iteration of the v2 latency loop. v1
(`.claude/skills/latency-iterate/`, ledger `loop-ledger.md`) ended
`stopped (exhausted)` with every micro stage PASSing and both e2e p50s floor-bound.
Its four autopsy findings are this loop's design constraints — internalize them
before anything else:

1. **±40 % e2e run-to-run variance at N=5 scenarios** made single-run deltas
   meaningless and 2×all-PASS statistically unreachable. → v2 never judges a fix on
   one run; it uses 3-run medians and record-paired deltas (§2).
2. **The bench never drives the Pipecat pipeline**, so `VOICE_LLM_MODEL`, VAD, the
   filler processor, and TTS provider flips were invisible. → lane Q builds a
   Pipecat-native bench before those knobs are touched (q0-4).
3. **The eval gate flakes ~1 test/run** (live-LLM tests + G-Eval rubrics near the
   0.8 cutoff), poisoning mandatory-eval accepts. → v2 splits hermetic (mandatory)
   from live (advisory, one retry); an eval reject requires a 2×-reproducible
   failure (q0-3, §6).
4. **Budget/provider changes are human-only**, and v1 treated that as a stop. → v2
   has a packet lane (H): it MEASURES the decision inputs, writes the packet, marks
   the item `awaiting-human`, and moves to the next eligible lane instead of dying.

Durable state: ledger `specs/features/2026-07-08-latency-engineering/loop-ledger-v2.md`
(same header discipline as v1; trust it over memory; update it last). The committed
protocol copy lives at
`specs/features/2026-07-08-latency-engineering/loop-v2-protocol.md` — on any drift
between this file and that one, the committed copy wins.

FINAL output line, exactly one of:

    LATENCY_LOOP2: CONTINUE (iteration <N> done: <fix-id> <accepted|reverted|blocked|awaiting-human>; next: <fix-id>)
    LATENCY_LOOP2: STOP (<reason>)

When driven by `/loop`: on CONTINUE schedule the next wakeup immediately; on STOP end
the loop. If invoked while the ledger says `stopped`, exit at §1 with zero side
effects.

## §1 Preconditions (abort loudly; never repair silently)

1. Ledger `state: stopped (…)` → STOP (already stopped). No ledger → iteration 1.
2. **Branch = `main`.** (v1 finding: branch isolation is fictional in this shared
   working tree; the collaborator commits to main continuously. Iterations are
   identified by commit-message prefix `latency-loop2 i<N>:`, greppable and
   bisectable, not by branch.)
3. **Collaborator-dirt rule** (replaces v1's blanket dirty-tree STOP, which caused
   the executor hand-off thrash): read `git status --porcelain`. Proceed iff the
   dirty files do NOT intersect this iteration's planned fix surface; list them in
   the ledger entry. If they DO intersect → pick the next queue item whose surface
   is clean; if none → STOP (surface contention — human intervention).
4. Keys: `.env` at repo root, loaded via `set -a; source .env; set +a`. A skip-warn
   from `make latency`/`make eval` is STOP (missing keys), never a pass.
5. Cost caps (ledger header): `iteration > 10` → STOP; `bench_runs_total >= 30` →
   STOP; `judged_eval_runs_total >= 12` → STOP.

## §2 MEASURE — the statistical protocol (v2's core)

- **One MEASUREMENT = 3 consecutive `make latency` runs** (foreground, never
  concurrent, nothing else heavy on the machine), `bench_runs_total += 3`. The
  stage value is the **median of the 3 p50s**; also record
  `noise_pct = (max−min)/median × 100` per stage.
- **Paired deltas**: compare candidate vs baseline per-record, matched on
  `(channel, scenario_id, turn_index)`, and report the **median of per-pair
  deltas** + the count of pairs improving vs regressing (sign test). Requires
  `latency_compare.py --paired` (built in q0-1; until it exists, only neutral-class
  fixes may be accepted).
- Baseline reuse: a prior measurement (all 3 reports still in `data/latency/`,
  < 24 h old, no bench-visible knob changed) is reusable. Bench-visible knobs:
  `LLM_PROVIDER`, `OPENAI_LLM_MODEL`, `OPENAI_TTS_MODEL`, `EMAIL/STT/TTS` env that
  the *bench primitives* read — `VOICE_*` knobs only after q0-4 lands.
- Hermetic guard first, every iteration: `.venv/bin/pytest tests/latency tests/voice -q`
  (red → STOP, tree already broken).

## §3 DIAGNOSE — decompose the floor, don't just rank stages

From the newest measurement's records, split each failing e2e p50 into its measured
segments: `submit→first_token` (prefill+TTFT), `first_token→first_sentence`
(clause accumulation), `first_sentence→first_audio` (raw TTS TTFB). Attribute the
gap-to-budget to segments; choose the fix whose lane targets the LARGEST segment.
v1's parting decomposition (2026-07-09): zero-tool web turn ≈ prefill-TTFT
0.9–1.3 s + clause 0.2–0.4 s + raw TTS 0.8–1.0 s vs a 2.0 s budget.

## §4 LANES + fix queue

Work the lanes in order Q → F → H, skipping items the ledger shows
done/blocked/reverted/awaiting-human. Within a lane, reordering requires a recorded
rationale (v1 §3.5 rule).

**Lane Q — measurement & gate quality (build these before spending on product fixes):**

| id | What | Class |
|----|------|-------|
| q0-1 | `latency_compare.py --paired`: record-matched median-of-deltas + sign counts, with offline tests | neutral |
| q0-2 | `make latency-3` (or `--repeat 3` on the bench): one command = one MEASUREMENT, medians + noise_pct in the report envelope, schema_version 3, tests | neutral |
| q0-3 | Eval-gate split: `make eval-hermetic` (recorded fixtures + hermetic rubrics — the loop's MANDATORY gate) vs `make eval-live` (live-LLM tests — advisory, auto-retry-once). Declared testing-evals delta; update its plan/validation in the same commit | neutral |
| q0-4 | Pipecat-native e2e bench: drive `build_pipeline_task` with a fake transport + REAL STT/LLM/TTS services over the scenario matrix; new report rows `pipecat_e2e_*`. Unlocks f5/f6 and closes v1's bench-fidelity gap for the phone channel | neutral |
| q0-5 | Perceived-audio metric: bench records BOTH `first_meaningful_audio_ms` (today's number) and `first_perceived_audio_ms` (greeting/filler cache hit) per turn — visibility only, no budget change | neutral |

**Lane F — floor reductions (one per iteration; regression test in the same commit;
hermetic eval mandatory):**

| id | Target segment | What |
|----|----------------|------|
| f1 | prefill-TTFT | Phase-gated system prompt: inject `SCHEDULING_CONTRACT` / `IMAGE_UPLOAD_CONTRACT` sections only once the conversation can need them (case-file-driven), cutting per-round prefill for the diagnostic head of every call |
| f2 | clause | Dynamic first-clause release: floor 40 → release ≥ 25 chars when the clause ends at punctuation; guarded by TTS-choppiness eval rubric staying green |
| f3 | raw TTS | Web-channel TTS provider adapter (`WEB_TTS_PROVIDER=openai|cartesia`, default unchanged): measure Cartesia vs OpenAI TTFB on the web path via paired A/B; DEFAULT FLIP IS h2's packet, not this fix |
| f4 | correctness re-land | Re-land v1's p0-4 flush (ack-before-tools) as neutral-plus: test-proven, zero-cost, inert only under today's model; protects the P0-4 contract when providers change |
| f5 | (needs q0-4) | `VOICE_LLM_MODEL` default `gpt-4o` → `gpt-4.1-mini` (USER-APPROVED 2026-07-09, conditional on evals green) — now accept-testable on the pipecat rows |
| f6 | (needs q0-4) | VAD stop-secs + filler timing tuning on the pipecat rows; never below `VAD_STOP_SECS_MIN_SAFE` |

**Lane H — human-decision packets (produce + `awaiting-human`, never decide):**

| id | Packet |
|----|--------|
| h1 | Budget semantics: measured floor decomposition (§3) + q0-5's perceived-vs-meaningful data + two concrete options (re-scope e2e p50s to floor+margin; or split budgets: perceived ≤ 800 ms hard / meaningful ≤ floor+10 % advisory). Written into `specs/latency/budgets.md` as a PROPOSAL block, ledger marks h1 awaiting-human |
| h2 | Web TTS default flip: f3's paired A/B table + eval quality scores per provider + cost note → proposal block + awaiting-human |

## §5 IMPROVE — exactly ONE fix-id, minimal diff, same-commit regression test.
Commit message `latency-loop2 i<N>: <fix-id> — <one line>`.
**Forbidden, no exceptions:** OpenAI Realtime API (constitution); editing any number
in `app/latency/budgets.py` / `specs/latency/budgets.md` outside an h1-approved
human decision; touching `.env`; concurrent live benches; weakening eval thresholds
or deleting failing tests to pass gates.

## §6 VALIDATE (cheap → expensive)

1. `make lint`; 2. full `make test` (a failure in collaborator-owned files you did
not touch: record + re-run that file once; if it passes in isolation it does not
block, per the v1 FK/flake precedent — but say so in the ledger);
3. Eval per q0-3 policy: hermetic mandatory (`judged_eval_runs_total += 1`); a
failure must reproduce on ONE retry of the failing test to count as a regression
(v1 flake lesson); live suite advisory. Until q0-3 lands, full `make eval` with the
same retry rule.
4. MEASUREMENT per §2 for latency-class fixes (neutral-class: reuse baseline).

## §7 ACCEPT / REVERT — noise-aware

- **Latency fixes**: accept iff the target segment/stage improves on the paired
  median by **> max(5 %, 1.5 × its measured noise_pct)** OR crosses FAIL→PASS on
  the 3-run median; AND no other stage regresses beyond its own noise band with a
  PASS→FAIL crossing; AND gates green (reproducible-eval rule).
- **Neutral fixes** (lane Q, f4): gates green + no PASS→FAIL crossing. No
  improvement bar.
- **Packets** (lane H): the packet file exists, is committed, and states its
  decision options — outcome `awaiting-human`.
- On reject: `git revert` (never reset), record the negative finding + retry
  hypothesis.

## §8 RECORD — append the ledger v2 entry (same JSON shape as v1 plus
`noise_pct`, `paired` stats, and `lane`), update header counters, commit
(separate commit; never rewrite shared history — v1 rule).

## §9 STOP / CONTINUE (in order)

1. **Success**: two consecutive MEASUREMENTS with every stage's 3-run median PASS →
   terminal gate-flip commit (Makefile `LATENCY_GATE_HARD=1` standard +
   testing-evals Decision 6 + runbook §4), `state: stopped (success)`.
2. **Lane-dry**: 2 consecutive no-accepts *within a lane* closes that lane; move to
   the next lane (do NOT global-stop — v1's mistake was conflating lane-dry with
   done).
3. **All lanes dry or awaiting-human** → `state: stopped (awaiting-human)` and the
   STOP line names the open packets — that is a hand-off, not a failure.
4. Cost caps (§1.5) → `state: stopped (cost-cap)`.
5. Otherwise CONTINUE, naming the next fix-id.
