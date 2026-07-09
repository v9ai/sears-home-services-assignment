# DeepSeek Agent LLM (direct, LlamaIndex function calling) — Requirements

## Source
User directive (2026-07-08):
> use deepseek call directly through llamaindex with function calling

Constitution-revising: changes the `tech-stack.md` Models table (updated in the same
commit per mission non-negotiable 6).

## Scope

### Included
- Agent LLM = **DeepSeek `deepseek-chat`**, called **directly** against
  `api.deepseek.com` through LlamaIndex's `DeepSeek` class
  (`llama-index-llms-deepseek`) — a `FunctionCallingLLM`, so the existing
  `FunctionAgent`/`AgentWorkflow` tool loop works unchanged.
- Swap confined to the single factory `app/agent/core.py:get_llm()` (every call site
  injects `llm` or falls through to the factory; tests inject fakes).
- `LLM_PROVIDER` env switch: `deepseek` (default) | `openai` (falls back to the proven
  `gpt-4o` path — demo-day resilience, one env var away).
- Env contract additions: `DEEPSEEK_API_KEY` (required by default path),
  `DEEPSEEK_MODEL` (optional, default `deepseek-chat`), `LLM_PROVIDER` (optional).
- Dependency: `llama-index-llms-deepseek` in `pyproject.toml`.

### Not included (deferred)
- TTS / STT / vision — stay OpenAI because DeepSeek has no audio or vision APIs; see
  `tech-stack.md` Models. DeepEval judging is **DeepSeek by default** under the
  Model-provider boundary, with `EVAL_JUDGE_PROVIDER=openai` as an explicit fallback.
- Gateways or local proxies (CF AI Gateway, localhost reasoner proxy) — the directive
  says *directly*; a gateway is a recorded future option, not a default.
- `deepseek-reasoner` — rejected (see Decisions), not offered as an env value.

### Contract shapes
- `get_llm() -> LLM` remains the only LLM construction site; frozen tool signatures
  (`COORDINATION.md` §2) untouched.
- Env: `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL?`, `LLM_PROVIDER?` (`.env.example` updated).
- Gates: `make lint`, `make test` (incl. `tests/test_llm_factory.py`) and the
  provider-allowlist guard that rejects OpenAI text-generation construction outside
  the explicit fallback paths.

## Decisions
1. **`deepseek-chat`, not `deepseek-reasoner`** — the tool loop requires function
   calling; DeepSeek's reasoner model does not support it. `DEEPSEEK_MODEL` allows
   forward-compatible overrides (e.g. future V3.x ids) without code change.
2. **Direct `api.deepseek.com` via the LlamaIndex `DeepSeek` class** — no gateway hop,
   no raw SDK: the class is OpenAI-compatible under the hood with
   `is_function_calling_model=True`, so `FunctionAgent` streaming + tool calling work
   as with OpenAI.
3. **`LLM_PROVIDER=openai` fallback retained** — the gpt-4o path already passed the
   group-7 smoke; keeping it switchable de-risks live testing (assignment §6 "working
   software").
4. **DeepSeek judge by default** — the Model-provider boundary applies to evals too:
   DeepEval uses `deepseek-chat` unless `EVAL_JUDGE_PROVIDER=openai` is explicitly set.
   Agent and judge sharing a provider creates self-grading risk; the mandatory canary
   suite is the standing mitigation and must fail bad transcripts on every run.
5. **Cost posture** — agent tokens move to DeepSeek's cheaper pricing, aligned with the
   assignment §7 free-tier/cost guidance; OpenAI spend narrows to voice/vision and
   explicit fallback runs.

## Architecture impact
- Constitution-revising: `tech-stack.md` Models table + Secrets, `COORDINATION.md` §1
  dependency list, `mission.md` cost bullet — all updated in this commit.
- Latency note: DeepSeek first-token latency is typically higher than `gpt-4o`; the
  Tier 1 budget (web e2e per `specs/latency/budgets.md`) is re-checked at the manual gate;
  if it fails consistently, the recorded mitigation is the `LLM_PROVIDER=openai`
  switch, not a new abstraction.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; builds on
  `2026-07-08-voice-diagnostic-core/` Decision 1 (FunctionAgent) — only the LLM row
  changes.
- Parallel/ownership: touches `app/agent/core.py` (voice-diagnostic-core's path) plus
  shared `pyproject.toml`/`.env.example` — executed as a lead change, not a parallel
  agent, since the parallel run has already merged.
