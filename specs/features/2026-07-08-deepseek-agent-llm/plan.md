# DeepSeek Agent LLM — Plan

Small, single-seam change; implement top to bottom.

## 1. Dependency
- [x] `llama-index-llms-deepseek` added to `pyproject.toml` dependencies; installed.

## 2. Factory swap
- [x] `app/agent/core.py:get_llm()`: `LLM_PROVIDER` branch — default `deepseek` →
      `DeepSeek(model=DEEPSEEK_MODEL or "deepseek-chat", api_key=DEEPSEEK_API_KEY)`;
      `openai` → previous `OpenAI(gpt-4o)` path. lru_cache retained.

## 3. Env contract
- [x] `.env.example`: `DEEPSEEK_API_KEY`, commented `DEEPSEEK_MODEL` /
      `LLM_PROVIDER` with the reasoner-unsupported note; local `.env` updated.

## 4. Tests
- [x] `tests/test_llm_factory.py`: default branch returns a function-calling
      `DeepSeek` on `deepseek-chat`; model env override; missing-key KeyError;
      `openai` fallback branch. No network.

## 5. Spec propagation (same commit)
- [x] `tech-stack.md` Models table + Agent framework note + Evaluation
      judge-diversity note + Secrets.
- [x] `COORDINATION.md` §1 dependency list.
- [x] `mission.md` cost bullet.
- [x] `voice-diagnostic-core/requirements.md` decision pointer.
- [x] `README.md` stack line.

## 6. Gates
- [x] `ruff check` + `ruff format --check` clean; full `pytest` green.
- [x] Manual live turn (validation.md) once a real `DEEPSEEK_API_KEY` is present —
      RUN 2026-07-08, PASS (4 tool calls in one turn; see validation.md Manual 1).
