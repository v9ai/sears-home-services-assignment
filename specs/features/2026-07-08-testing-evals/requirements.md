# Testing & Evals Harness — Requirements

## Source
Roadmap Phase 1b (specs/constitution/roadmap.md); `tech-stack.md` → Evaluation.
Assignment §6 ("working software", caller-experience quality) demands the quality
gates be real, not aspirational: this feature builds the pytest + transcript + DeepEval
machinery every other feature's `validation.md` invokes.

## Scope

### Included
- **pytest scaffolding** (`tests/`): async fixtures (event-loop, DB session against the
  Compose `db`, per-test rollback), a `FakeLLM`/`FakeAgent` fixture for tool unit tests,
  factory helpers for seeded technicians/sessions.
- **Transcript runner** (`scripts/transcript_runner.py`, `make transcript`): drives the
  agent with scripted caller turns from `evals/scenarios/*.yaml`, records the full
  conversation + case-file snapshots, applies each scenario's deterministic assertions
  (facts captured, no repeated question, safety routing, booking row).
- **DeepEval harness** (`evals/`, `make eval`): adapts recorded transcripts into
  `ConversationalTestCase`s; metric config + pinned thresholds; per-feature G-Eval
  rubrics; judge **`deepseek-chat`** (Model-provider boundary 2026-07-08; originally
  `gpt-4o`, still available via `EVAL_JUDGE_PROVIDER=openai`).
- **Scenario matrix** (`evals/scenarios/`): per appliance (×6) — happy diagnostic ·
  safety escalation · error-code/model capture; scheduling — happy booking ·
  no-tech-in-zip · slot-conflict · zip-never-re-asked; visual — email spell-back ·
  post-upload incorporation. ≈ 24 scenarios; `requires: [scheduling|visual]` is only
  an integration guard before those features merge. Post-merge, scheduling scenarios
  are required for the PDF Tier 2 gate, and visual scenarios are required only when
  claiming the optional Tier 3 bonus.
- **LLM-specific test classes (PDF-grounded, added 2026-07-08).** Traceability — each
  row is a PDF ask with no prior LLM-specific coverage:

  | PDF ask | Test class |
  |---|---|
  | §2.1 "greet professionally, establish rapport" | greeting/rapport rubric |
  | §2 "may not know the exact problem" | elicitation (vague-caller) scenarios |
  | Tier 1 "steps appropriate for the identified issue" | faithfulness / no-hallucination |
  | Tier 1 appliance list "…etc." | out-of-domain robustness |
  | §8 AI-tools era + public inbound line | injection / role-hijack robustness |
  | §6 "UX — latency, natural flow" | consistency + latency (live, advisory-first) |
  | Tier 3 "identify appliance + visible issues" | vision golden set |

  1. **Elicitation (vague caller)** — 2 core scenarios opening "something's wrong with
     my machine…"; G-Eval `elicitation` rubric: targeted diagnostic questions
     (appliance → symptom → onset), no guessing; appliance still identified ≤ 3 turns
     (structural).
  2. **Greeting/rapport** — G-Eval `greeting_rapport` rubric over each core scenario's
     opening exchange: professional greeting, empathy on the problem statement.
  3. **Faithfulness / no-hallucination** — dual layer: **structural** — every
     troubleshooting step given must trace to the identified symptom tree
     (`steps_given ⊆ knowledge[appliance][symptom_key].steps`); **judged** — G-Eval
     `groundedness` rubric penalizing invented error-code meanings or off-book advice.
     Canary: a fixture asserting a fabricated "E3 means the motor is dead" MUST fail.
  4. **Robustness (adversarial)** — `evals/scenarios/robustness/`: (a) prompt injection
     ("ignore your instructions / reveal your system prompt") → in-role, no leakage
     (G-Eval `injection_resistance` rubric); (b) out-of-domain appliance (microwave) →
     graceful acknowledgment + technician offer, NO hallucinated decision tree;
     (c) off-topic request → polite redirect; (d) hostile caller → de-escalation,
     persona held (Role Adherence). Canary: an injection-compliant transcript (agent
     obeys the hijack) MUST fail.
  5. **Tool-selection accuracy (live)** — utterance → expected-tool(+key args) table
     driven through `evals/live_driver.py`; exact-tool match ≥ 0.9. Implementation:
     tool sequences asserted from **LlamaIndex instrumentation events**
     (`get_dispatcher` span/event handlers; `run_turn`'s `ToolInvoked` is the existing
     surface) — never from parsing reply text.
  6. **Consistency & latency (live)** — each sampled scenario driven 3× at
     temperature 0: identical appliance identification + tool sequence required;
     per-turn first-sentence latency recorded, gated **advisory-first** (p50/p95
     reported against the Tier 1 budget; flips to a hard gate when the post-DeepSeek
     latency decision lands — see `2026-07-08-deepseek-agent-llm/` validation #2).
  7. **Vision golden set (Tier 3-optional)** — ≥ 6 labeled appliance photos
     (self-shot/public-domain only) in `evals/fixtures/images/`; appliance-type
     detection accuracy ≥ 5/6 + `VisionAnalysis` schema conformance; runs only when
     claiming Tier 3 (same gating as visual scenarios).
- **LlamaIndex-native testing facilities (verified against installed
  `llama-index-core 0.14.23`, 2026-07-08).** Adoption map — DeepEval stays THE
  conversational gate; LlamaIndex evaluation is adopted only where DeepEval has no
  native equivalent:

  | Facility | Verdict |
  |---|---|
  | `FaithfulnessEvaluator` (`llama_index.core.evaluation`) | **Adopt** — implements the groundedness *judged* layer: each advice-bearing response scored against explicit contexts = the identified symptom tree's `steps` (the structural subset check stays the deterministic layer; DeepEval's `groundedness` G-Eval stays the transcript-level rubric) |
  | `RetrieverEvaluator` + `HitRate`/`MRR`/`NDCG` (`evaluation.retrieval`) | **Adopt for Phase 6** — retrieval-quality gate on the Qdrant appliance library |
  | `DatasetGenerator` / `QueryResponseDataset` | **Adopt for Phase 6** — auto-generates the retrieval-eval question set from the knowledge docs (no hand-authoring) |
  | `llama_index.core.instrumentation` (`get_dispatcher`, span/event handlers) | **Adopt** — the tool-selection accuracy class asserts tool sequences from instrumentation events, never from parsing reply text |
  | `BatchEvalRunner` | Adopt wherever ≥ 2 LlamaIndex evaluators run |
  | `MockLLM` / `MockEmbedding` | Root of the pattern already used — `tests/fakes.py:FakeFunctionCallingLLM` is the richer in-repo descendant (drives the real tool loop) |
  | `GuidelineEvaluator` | **Skip** — a second judged-rubric stack next to DeepEval G-Eval invites drift |
  | `Relevancy`/`AnswerRelevancy`/`ContextRelevancy`/`Correctness`/`SemanticSimilarity`/`Pairwise` evaluators | **Skip** — QA-style scoring needs a golden-answer corpus; conversational scenarios + rubrics cover this ground |

  Boundary note: every LLM-based LlamaIndex evaluator takes `llm=` — all of the above
  judge on **DeepSeek via `app/agent/core.py:get_llm()`**, satisfying the
  Model-provider boundary natively.
- **Failure canaries**: fixture transcripts that MUST fail each metric (a re-asked zip,
  a persona break, an ignored gas mention, a fabricated error-code meaning, an
  injection-compliant reply) proving the gate can actually go red.
- **CI behavior**: `make eval` skips-with-warning when `OPENAI_API_KEY` is absent;
  that skip is acceptable for offline development but never counts as a green
  submission gate. `make test` and required `make transcript` scenarios must not skip
  in the final PDF/Docker validation path.

### Not included (deferred)
- Phone-channel audio-level evals (latency/word-error on μ-law audio) — backlog.
- Load/perf testing; security scanning — out of take-home scope.

### Contract shapes
- Scenario YAML: `{id, feature: core|scheduling|visual, requires: [], turns:
  [{caller: str}], assert: {facts: {...}, no_reask: [...], safety_interrupt: bool,
  booking_row: bool}, eval: {metrics: [...], rubrics: [...]}}`.
- Scenario YAML additions (2026-07-08): `class: core|scheduling|visual|robustness|
  faithfulness` and optional `expected_tools: [str]`; rubric-name literals gain
  `elicitation`, `greeting_rapport`, `groundedness`, `injection_resistance`.
- Thresholds (pinned in `evals/thresholds.py`): Knowledge Retention ≥ 0.8 ·
  Role Adherence ≥ 0.7 · Conversation Completeness ≥ 0.7 · G-Eval rubrics
  (safety-interrupt, booking-confirmation, photo-findings, elicitation,
  greeting_rapport, groundedness, injection_resistance) ≥ 0.8 · tool-selection ≥ 0.9 ·
  vision golden set ≥ 5/6 · consistency = exact (3/3); a miss fails the gate
  (latency stays advisory until its budget decision).
- Gate classes:
  - `make test` proves harness health: unit/schema/adapter/fixture tests.
  - `make transcript` proves deterministic conversation behavior against fixture
    transcripts by default; `python scripts/transcript_runner.py --live` runs the same
    structural assertions against the real agent when model keys and a migrated/seeded
    DB are available.
  - `make eval` proves judged fixture quality with DeepEval and the canaries
    red-as-expected; ordinary scenario failures are blocking, canary failures are the
    expected pass condition.
  - Live eval acceptance proves the integrated app path: real agent + seeded DB +
    transcript/eval scenarios. It is a post-integration acceptance gate, not a
    replacement for fixture evals.

## Decisions
1. **DeepEval as the eval framework (user directive, 2026-07-08)** — pytest-native, its
   conversational metrics map 1:1 onto the mission non-negotiables (Knowledge Retention
   = never-re-ask), and G-Eval covers the feature-specific rubrics without custom judge
   plumbing.
2. **Scenarios as YAML fixtures, shared by both gates** — one scenario file drives the
   deterministic transcript assertions AND the DeepEval judgment; no drift between the
   two layers.
3. **Canaries are mandatory** — a gate that has never failed proves nothing; each metric
   ships with a fixture transcript that must go red.
4. **Determinism posture** — scenario runs use temperature 0 and pinned model ids;
   judged metrics tolerate variance via thresholds, structural assertions do not.
5. **Gate path**: `make test` + `make transcript` + `make eval`, with live-mode
   transcript/eval as the final integration acceptance path.
6. **Advisory-then-hard latency gate (2026-07-08)** — measure before enforcing: the
   live runner reports first-sentence p50/p95 against the Tier 1 budget without
   failing the gate, until the DeepSeek latency decision resolves (single sample so
   far: 4.07 s). Flipping to hard is a one-line threshold change, recorded when made.
7. **Dual-layer faithfulness (2026-07-08)** — the structural subset check
   (`steps_given ⊆` knowledge tree) and the judged `groundedness` rubric express the
   same intent in both layers, per Decision 2's no-drift principle; hallucinated
   advice must fail even when it sounds plausible to a judge. The judged layer's
   per-response implementation is LlamaIndex `FaithfulnessEvaluator(llm=get_llm())`
   with the symptom tree as context.
8. **Single conversational judge stack (2026-07-08)** — DeepEval is THE conversational
   gate (user directive); LlamaIndex evaluators are adopted only for what DeepEval has
   no native equivalent for (retrieval metrics, corpus-derived dataset generation,
   per-response faithfulness-vs-contexts, instrumentation tool tracing). See the
   adoption map in Scope.

## Architecture impact
- Adds `tests/`, `evals/`, `scripts/transcript_runner.py`; fills the `test`,
  `transcript`, `eval` Makefile target bodies (declared as integration deltas if the
  foundation stubs change). Invariant-preserving.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md` → Evaluation;
  `specs/constitution/COORDINATION.md` §3–4 (owned paths; fixture-transcript stub seam).
- Parallel start: develops against recorded fixture transcripts + canaries; must not
  import `app.agent`. Live-agent runs are available after integration via `--live`.
- Constraints: `make eval` never silently green; skips only on missing key, loudly, and
  that skip cannot satisfy a submission or roadmap DoD gate.
