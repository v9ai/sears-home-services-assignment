# Sears Home Services — task runner (tech-stack.md → Make commands).
# Foundation ships every target as a no-op TODO; the owning feature (COORDINATION.md
# §3) fills in the real body. Do not add real logic outside your owned feature.

# Prefer the repo venv when present, so `make test`/`lint`/... work without activation.
BIN := $(shell [ -x .venv/bin/python ] && echo .venv/bin/)

.PHONY: up dev migrate seed test lint transcript eval eval-hermetic eval-live ingest deploy latency phone-debug booking-bench stutter appt-req

up: ## docker compose up --build — single-command launch
	docker compose up --build

dev: ## local uvicorn with reload against the Compose db
	$(BIN)uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate: ## alembic upgrade head
	$(BIN)alembic upgrade heads

seed: ## idempotent technician/slot seed
	$(BIN)python -m app.db.seed

test: stutter ## stutter bench (hard gate) + pytest
	$(BIN)pytest tests -q

lint: ## ruff check + ruff format --check
	$(BIN)ruff check .
	$(BIN)ruff format --check .

transcript: ## scripted text-mode E2E conversation gate
	$(BIN)python scripts/transcript_runner.py

eval: eval-hermetic eval-live ## full eval gate: hermetic (hard) + live (advisory) — q0-3 split

eval-hermetic: ## MANDATORY eval lane: recorded fixtures + judged rubrics, no live agent drives
	@KEY_ENV=$${EVAL_JUDGE_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ]; then \
		echo "WARNING: $$NEEDED not set - skipping make eval-hermetic (DeepEval judge, provider $${EVAL_JUDGE_PROVIDER:-deepseek})."; \
		echo "This is a SKIP, not a pass — see tech-stack.md -> Evaluation."; \
	else \
		$(BIN)pytest evals -q -m "not live"; \
	fi

eval-live: ## ADVISORY eval lane: live agent/LLM drives; failures retried once, never fail the build
	@KEY_ENV=$${EVAL_JUDGE_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ]; then \
		echo "WARNING: $$NEEDED not set - skipping make eval-live."; \
	else \
		$(BIN)pytest evals -q -m live \
		|| { echo "eval-live: retrying failed live tests once (stochastic live-LLM lane)..."; \
		     $(BIN)pytest evals -q -m live --last-failed; } \
		|| echo "WARNING: eval-live still red after retry — ADVISORY lane, not failing the build; investigate before release."; \
	fi

ingest: ## build the local Qdrant appliance-library index (Phase 6, opt-in)
	$(BIN)python scripts/ingest_library.py

phone-debug: ## Twilio CLI debug toolkit — e.g. make phone-debug cmd="status"
	$(BIN)python scripts/twilio_debug.py $(cmd)

latency: ## stage + end-to-end latency bench, writes data/latency/{ts}.json (HARD gate since 2026-07-10)
	@KEY_ENV=$${LLM_PROVIDER:-deepseek}; \
	if [ "$$KEY_ENV" = "openai" ]; then NEEDED=OPENAI_API_KEY; NEEDED_VAL="$$OPENAI_API_KEY"; \
	else NEEDED=DEEPSEEK_API_KEY; NEEDED_VAL="$$DEEPSEEK_API_KEY"; fi; \
	if [ -z "$$NEEDED_VAL" ] || [ -z "$$OPENAI_API_KEY" ]; then \
		echo "WARNING: $$NEEDED and/or OPENAI_API_KEY not set - skipping make latency (LLM + STT/TTS keys required)."; \
		echo "This is a SKIP, not a pass — see tech-stack.md -> Evaluation."; \
	else \
		LATENCY_GATE_HARD=$${LATENCY_GATE_HARD:-1} $(BIN)python scripts/latency_bench.py $(args); \
	fi

booking-bench: ## adaptive live booking-quality bench, writes data/booking_quality/{ts}.json
	$(BIN)python scripts/booking_quality_bench.py $(args)

stutter: ## hermetic phone-audio stutter bench (keyless, HARD gate since 2026-07-10), writes data/stutter/{ts}.json
	$(BIN)python scripts/stutter_bench.py

appt-req: ## hermetic appointment-requirements bench (keyless, soft gate until gate-flip), writes data/appt_req/{ts}.json
	$(BIN)python scripts/appointment_requirements_bench.py

deploy: ## wrangler deploy of the app to Cloudflare Containers
	@echo "[deploy] app -> wrangler.app.toml"
	cd cloudflare && npm install && npx wrangler deploy --config ../wrangler.app.toml
