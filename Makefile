.PHONY: install dev dev-local api web worker test test-pg test-all lint typecheck lint-imports migrate seed plans-sync seed-dev docker-down docker-prune coverage

install: ## Install dependencies with uv
	uv sync --all-groups

dev: ## Full stack via docker compose
	docker compose up --build

dev-local: ## Hot-reload api + web against compose postgres/redis
	docker compose up -d postgres redis
	$(MAKE) migrate
	uv run uvicorn apps.api.main:app --reload --port 8000

api: ## Run API locally (expects compose postgres/redis)
	uv run uvicorn apps.api.main:app --reload --port 8000

worker: ## Run arq worker locally
	uv run synapse-worker

web: ## Run Next.js console locally
	cd apps/web && pnpm dev

test: ## Fast unit tests (no database)
	uv run pytest -m 'not pg' --no-cov

test-pg: ## Integration tests against compose postgres
	uv run pytest -m pg --no-cov

test-all: ## Everything, with coverage gate
	uv run pytest -m "" --cov=src/synapse_saas --cov-fail-under=80

lint: ## Ruff + import-linter
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run lint-imports

typecheck: ## mypy strict
	uv run mypy src

migrate: ## Apply Alembic migrations
	uv run alembic upgrade head

seed: ## Seed permissions, system roles, and sync plan catalog
	uv run synapse-cli seed

seed-dev: ## Seed demo org/users for local development
	uv run synapse-cli seed --dev

plans-sync: ## Sync config/plans.yaml to database
	uv run synapse-cli plans sync

docker-down: ## Stop compose stack
	docker compose down

docker-prune: ## Stop compose stack and delete volumes (DESTROYS DATA)
	docker compose down -v

coverage: ## Coverage report
	uv run pytest --cov-report=html --no-cov-on-fail
	@echo "HTML report: htmlcov/index.html"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
