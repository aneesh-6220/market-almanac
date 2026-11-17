# Market Almanac developer commands. Run `make help` for a list.
SHELL := /bin/bash
WEB := apps/web

.PHONY: help setup demo api web dev test test-live test-web e2e e2e-live bundle lint format typecheck build docker-up docker-down doctor clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python (uv) and web (npm) dependencies
	uv sync
	npm --prefix $(WEB) ci

demo: ## Initialise the database and seed the SYNTHETIC demo (offline)
	MARKET_ALMANAC_MODE=demo uv run market-almanac db-init
	uv run market-almanac demo-seed

api: ## Run the API on :8000 (mode from MARKET_ALMANAC_MODE, default demo)
	uv run uvicorn market_almanac_api.main:app --reload --port 8000

web: ## Run the web app on :3000
	npm --prefix $(WEB) run dev -- --port 3000

dev: ## Run API and web together
	@trap 'kill 0' INT TERM; $(MAKE) api & $(MAKE) web & wait

doctor: ## Check configuration, storage, database and live provider health
	uv run market-almanac doctor --live

test: ## Python unit, integration and scientific-correctness tests (offline)
	uv run pytest

test-live: ## Opt-in tests against the real provider APIs (needs network and credentials)
	uv run pytest -m live

test-web: ## Web component tests (Vitest)
	npm --prefix $(WEB) test

e2e: ## End-to-end tests on the synthetic demo (Playwright; run `make demo` first)
	npm --prefix $(WEB) run test:e2e

e2e-live: ## End-to-end tests on real data (install the public data bundle first, see README)
	E2E_MODE=live npm --prefix $(WEB) run test:e2e

bundle: ## Package live lake snapshots, catalog and experiment results into dist/ (verified archive)
	MARKET_ALMANAC_MODE=live uv run market-almanac bundle-export --out dist

lint: ## Ruff, mypy, ESLint and TypeScript
	uv run ruff check .
	uv run mypy
	npm --prefix $(WEB) run lint
	npm --prefix $(WEB) run typecheck

format: ## Auto-format Python
	uv run ruff check --fix .
	uv run ruff format .

build: ## Production build of the web app
	npm --prefix $(WEB) run build

docker-up: ## Start PostgreSQL, API and web with Docker Compose (demo mode)
	docker compose up --build -d

docker-down: ## Stop the Compose stack
	docker compose down

clean: ## Remove caches and build output (keeps data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache $(WEB)/.next $(WEB)/test-results
