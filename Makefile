# Sears Home Services — task runner (tech-stack.md → Make commands).
# Foundation ships every target as a no-op TODO; the owning feature (COORDINATION.md
# §3) fills in the real body. Do not add real logic outside your owned feature.

.PHONY: up dev web-dev migrate seed test lint transcript eval deploy

up: ## docker compose up --build — single-command launch
	docker compose up --build

dev: ## local uvicorn with reload against the Compose db
	@echo "TODO: dev — owned by voice-diagnostic-core"

web-dev: ## next dev in web/ against the local backend
	@echo "TODO: web-dev — owned by voice-diagnostic-core"

migrate: ## alembic upgrade head
	@echo "TODO: migrate — owned by voice-diagnostic-core"

seed: ## idempotent technician/slot seed
	@echo "TODO: seed — owned by technician-scheduling"

test: ## pytest
	@echo "TODO: test — owned by testing-evals"

lint: ## ruff check + ruff format --check
	@echo "TODO: lint — owned by testing-evals"

transcript: ## scripted text-mode E2E conversation gate
	@echo "TODO: transcript — owned by testing-evals"

eval: ## DeepEval conversational gate over the transcript scenarios
	@echo "TODO: eval — owned by testing-evals"

deploy: ## wrangler deploy of app + web to Cloudflare Containers
	@echo "[deploy] app -> wrangler.app.toml"
	cd cloudflare && npm install && npx wrangler deploy --config ../wrangler.app.toml
	@echo "[deploy] web -> wrangler.web.toml (set NEXT_PUBLIC_* to the app Worker's URL first)"
	cd cloudflare && npx wrangler deploy --config ../wrangler.web.toml
