PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
UV ?= uv

.DEFAULT_GOAL := help

.PHONY: help setup run test smoke lint format typecheck openapi scan clean

help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install runtime + dev dependencies
	$(UV) venv --python $(PYTHON) $(VENV)
	$(UV) pip install --python $(BIN)/python -e ".[dev]"
	@echo "Run 'make run' to start the API on http://127.0.0.1:8000"

run: ## Start the API locally with reload
	$(BIN)/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test: ## Run the offline test suite (unit, API and politeness)
	$(BIN)/pytest

test-live: ## Run the test suite including live tests that hit the real site
	$(BIN)/pytest --live

smoke: ## Run the live smoke test against a running server
	$(BIN)/python scripts/smoke_test.py

lint: ## Lint, format-check and type-check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy app

format: ## Apply ruff formatting and autofixes
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

openapi: ## Export the OpenAPI document to docs/openapi.json
	$(BIN)/python -c "import json; from app.main import app; \
	print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > docs/openapi.json
	@echo "wrote docs/openapi.json"

scan: ## Scan the repository for secrets, tokens, e-mails and personal data
	$(BIN)/python scripts/secret_scan.py

clean: ## Remove caches and the virtualenv
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
