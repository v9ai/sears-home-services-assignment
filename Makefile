# Sears Home Services — task runner (tech-stack.md → Make commands).
# Foundation ships every target as a no-op TODO; the owning feature (COORDINATION.md
# §3) fills in the real body. Do not add real logic outside your owned feature.

.PHONY: up dev web-dev migrate seed test lint transcript eval deploy

up: ## docker compose up --build — single-command launch
	@echo "TODO: up — owned by deployment-deliverables"

dev: ## local uvicorn with reload against the Compose db
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web-dev: ## next dev in web/ against the local backend
	cd web && npm run dev

migrate: ## alembic upgrade head
	alembic upgrade heads

seed: ## idempotent technician/slot seed
	python -m app.db.seed

test: ## pytest
	@echo "TODO: test — owned by testing-evals"

lint: ## ruff check + ruff format --check
	@echo "TODO: lint — owned by testing-evals"

transcript: ## scripted text-mode E2E conversation gate
	@echo "TODO: transcript — owned by testing-evals"

eval: ## DeepEval conversational gate over the transcript scenarios
	@echo "TODO: eval — owned by testing-evals"

deploy: ## wrangler deploy of app + web to Cloudflare Containers
	@echo "TODO: deploy — owned by deployment-deliverables"
