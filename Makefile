# Sears Home Services — task runner (tech-stack.md → Make commands).
# Foundation ships every target as a no-op TODO; the owning feature (COORDINATION.md
# §3) fills in the real body. Do not add real logic outside your owned feature.

# Prefer the repo venv when present, so `make test`/`lint`/... work without activation.
BIN := $(shell [ -x .venv/bin/python ] && echo .venv/bin/)

.PHONY: up dev web-dev migrate seed test lint transcript eval eval-voice ingest deploy latency

up: ## docker compose up --build — single-command launch
	docker compose up --build

dev: ## local uvicorn with reload against the Compose db
	$(BIN)uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web-dev: ## next dev in web/ against the local backend
	cd web && npm run dev

migrate: ## alembic upgrade head
	$(BIN)alembic upgrade heads

seed: ## idempotent technician/slot seed
	$(BIN)python -m app.db.seed

test: ## pytest
	$(BIN)pytest tests -q

lint: ## ruff check + ruff format --check
	$(BIN)ruff check .
	$(BIN)ruff format --check .

transcript: ## scripted text-mode E2E conversation gate
	$(BIN)python scripts/transcript_runner.py

eval: ## DeepEval conversational gate over the transcript scenarios
	@KEY_ENV=$${EVAL_JUDGE_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ]; then \
		echo "WARNING: $$NEEDED not set - skipping make eval (DeepEval judge, provider $${EVAL_JUDGE_PROVIDER:-deepseek})."; \
		echo "This is a SKIP, not a pass — see tech-stack.md -> Evaluation."; \
	else \
		$(BIN)pytest evals -q; \
	fi

eval-voice: ## Pipecat voice-channel gates: offline voice tests + DeepEval spoken-output eval
	$(BIN)pytest tests/voice -q
	@KEY_ENV=$${EVAL_JUDGE_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ]; then \
		echo "WARNING: $$NEEDED not set - skipping voice DeepEval (judge, provider $${EVAL_JUDGE_PROVIDER:-deepseek})."; \
		echo "This is a SKIP, not a pass — see tech-stack.md -> Evaluation."; \
	else \
		$(BIN)pytest evals/test_voice_conversations.py -q; \
	fi

ingest: ## build the local Qdrant appliance-library index (Phase 6, opt-in)
	$(BIN)python scripts/ingest_library.py

latency: ## stage + end-to-end latency bench, writes data/latency/{ts}.json
	@KEY_ENV=$${LLM_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ] || [ -z "$$OPENAI_API_KEY" ]; then \
		echo "WARNING: $$NEEDED and/or OPENAI_API_KEY not set - skipping make latency (LLM + STT/TTS keys required)."; \
		echo "This is a SKIP, not a pass — see tech-stack.md -> Evaluation."; \
	else \
		$(BIN)python scripts/latency_bench.py; \
	fi

deploy: ## wrangler deploy of app + web to Cloudflare Containers
	@echo "[deploy] app -> wrangler.app.toml"
	cd cloudflare && npm install && npx wrangler deploy --config ../wrangler.app.toml
	@echo "[deploy] web -> wrangler.web.toml (point [containers.image_vars] NEXT_PUBLIC_* at the deployed app Worker URL first)"
	cd cloudflare && npx wrangler deploy --config ../wrangler.web.toml
