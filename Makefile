# Paceboard — local-first fitness analytics over Garmin MCP and Strava.
.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv run --extra paceboard

.PHONY: help install dev api web garmin-mcp migrate sync backfill smoke \
        test test-backend test-frontend lint typecheck build e2e check clean allowlist

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and dashboard dependencies
	uv sync --extra paceboard
	cd dashboard && npm install

dev: ## Start the API and dashboard together (loopback only)
	./scripts/dev.sh

garmin-mcp: ## Start the Garmin MCP server with the read-only allowlist
	./scripts/garmin-mcp-readonly.sh

api: ## Start only the Paceboard API
	$(UV) paceboard-api serve

web: ## Start only the dashboard
	cd dashboard && npm run dev

migrate: ## Apply database migrations
	$(UV) paceboard-api migrate

sync: ## Sync the recent window from every configured provider
	$(UV) paceboard-api sync --mode incremental

backfill: ## Backfill the configured history window
	$(UV) paceboard-api sync --mode backfill

smoke: ## Read-only Garmin MCP connectivity check
	$(UV) paceboard-api smoke

allowlist: ## Regenerate the Garmin read-only launch script from the catalog
	$(UV) python scripts/generate_garmin_allowlist.py

test-backend: ## Run the Python test suite (Garmin MCP + Paceboard)
	$(UV) pytest -q -m "not e2e"

test-frontend: ## Type-check and lint the dashboard
	cd dashboard && npm run typecheck && npm run lint

e2e: ## Run the Playwright end-to-end test in fixture mode
	cd dashboard && npm run test:e2e

build: ## Production build of the dashboard
	cd dashboard && npm run build

test: test-backend test-frontend ## Backend tests plus frontend checks

check: test build ## Everything CI runs

clean: ## Remove build artifacts (never the database)
	rm -rf dashboard/dist dashboard/playwright-report dashboard/test-results
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
