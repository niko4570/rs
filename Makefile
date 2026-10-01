# Research Summarizer — local development tasks
#
# Quick start:
#   make install   # one-time: create venv + install backend & frontend deps
#   make dev       # run backend (127.0.0.1:8000) and frontend (localhost:5173) together
#
# Run `make` or `make help` to list every target.

VENV     := .venv
PYTHON   := $(VENV)/bin/python
UVICORN  := $(VENV)/bin/uvicorn
PYTEST   := $(VENV)/bin/pytest
RUFF     := $(VENV)/bin/ruff

APP      := research_summarizer.api:app
HOST     := 127.0.0.1
PORT     := 8000

FRONTEND := frontend

.DEFAULT_GOAL := help

# ------------------------------------------------------------------ setup ---

.PHONY: install
install: install-backend install-frontend ## Install backend and frontend dependencies

.PHONY: install-backend
install-backend: ## Create the venv and install the Python package (editable)
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .

.PHONY: install-frontend
install-frontend: ## Install frontend npm dependencies
	cd $(FRONTEND) && npm install

# -------------------------------------------------------------------- run ---

.PHONY: dev
dev: check-venv check-frontend ## Start backend + frontend together (Ctrl+C stops both)
	@echo "▶ backend  → http://$(HOST):$(PORT)"
	@echo "▶ frontend → http://localhost:5173"
	@echo "  Press Ctrl+C to stop both."
	@trap 'kill $$BACKEND_PID $$FRONTEND_PID 2>/dev/null' INT TERM EXIT; \
	$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --reload & \
	BACKEND_PID=$$!; \
	( cd $(FRONTEND) && npm run dev ) & \
	FRONTEND_PID=$$!; \
	wait

.PHONY: backend
backend: check-venv ## Start only the backend API
	$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --reload

.PHONY: frontend
frontend: check-frontend ## Start only the frontend dev server
	cd $(FRONTEND) && npm run dev

# ------------------------------------------------------------------- test ---

.PHONY: test
test: check-venv ## Run the full backend test suite
	$(PYTEST) -q

.PHONY: test-api
test-api: check-venv ## Run only the API adapter tests
	$(PYTEST) tests/test_api.py -q

.PHONY: lint
lint: check-venv ## Run Ruff over the Python sources and tests
	$(RUFF) check research_summarizer tests

.PHONY: typecheck
typecheck: check-frontend ## Type-check the frontend (tsc --noEmit)
	cd $(FRONTEND) && npm run typecheck

.PHONY: build
build: check-frontend ## Production-build the frontend
	cd $(FRONTEND) && npm run build

.PHONY: check
check: lint test build ## Run lint, backend tests, and frontend build

# ------------------------------------------------------------------ clean ---

.PHONY: clean
clean: ## Remove build/test caches (keeps .venv and node_modules)
	rm -rf $(FRONTEND)/dist .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# --------------------------------------------------------------- helpers ----

.PHONY: help
help: ## Show this help
	@echo "Research Summarizer — available targets:"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  make %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Example:  make dev   # backend :8000  +  frontend :5173"

.PHONY: check-venv
check-venv:
	@test -x $(UVICORN) || { \
		echo "✖ Missing virtualenv at $(VENV). Run 'make install-backend' first." >&2; \
		exit 1; \
	}

.PHONY: check-frontend
check-frontend:
	@test -d $(FRONTEND)/node_modules || { \
		echo "✖ Missing $(FRONTEND)/node_modules. Run 'make install-frontend' first." >&2; \
		exit 1; \
	}
