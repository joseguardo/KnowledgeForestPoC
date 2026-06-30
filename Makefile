# ── KnowledgeForest ──────────────────────────────────────────────────

.PHONY: frontend backend dev install install-frontend install-backend test lint clean

# ── Run services ─────────────────────────────────────────────────────

frontend: ## Start Vite dev server (React + Three.js)
	npm run dev

backend: ## Start FastAPI ingestion pipeline
	cd pipeline && source .venv/bin/activate && uvicorn pipeline.main:app --reload --port 8080

dev: ## Start both frontend and backend in parallel
	@echo "Starting frontend (port 5173) and backend (port 8080)..."
	@trap 'kill 0' INT TERM; \
	(npm run dev) & \
	(cd pipeline && source .venv/bin/activate && uvicorn pipeline.main:app --reload --port 8080) & \
	wait

# ── Setup ────────────────────────────────────────────────────────────

install: install-frontend install-backend ## Install all dependencies

install-frontend: ## Install frontend (npm) dependencies
	npm install

install-backend: ## Create venv and install pipeline dependencies
	cd pipeline && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# ── Quality ──────────────────────────────────────────────────────────

test: ## Run pipeline tests
	cd pipeline && source .venv/bin/activate && python -m pytest tests/ -v

lint: ## Lint pipeline code
	cd pipeline && source .venv/bin/activate && ruff check pipeline/ tests/

# ── Cleanup ──────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	rm -rf pipeline/.venv pipeline/.pytest_cache pipeline/__pycache__
	rm -rf node_modules dist

# ── Help ─────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
