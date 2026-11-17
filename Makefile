.DEFAULT_GOAL := help
VENV ?= .venv
BIN  := $(VENV)/bin
DBT  := $(BIN)/dbt
DBT_FLAGS := --project-dir dbt --profiles-dir dbt

.PHONY: help setup extract build freshness export pipeline dashboard test lint demo unit figures snapshot format docs clean

help: ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install everything
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dashboard,dev,figures]" -c constraints.txt

extract: ## Load raw data from the API (first run backfills ~25M rows, about 30 min)
	$(BIN)/lvm extract

build: ## Run dbt seeds, models and tests
	@mkdir -p data
	$(DBT) build $(DBT_FLAGS)

freshness: ## Check how stale the source is
	@mkdir -p data
	$(DBT) source freshness $(DBT_FLAGS)

export: ## Publish marts as Parquet for the dashboard
	$(BIN)/lvm export

pipeline: extract freshness build export ## Run the whole pipeline end to end

dashboard: ## Start the Streamlit dashboard
	$(BIN)/streamlit run dashboard/app.py

test: ## Unit tests, dbt unit tests and the end-to-end test on fixtures
	$(BIN)/pytest

lint: ## Static checks: ruff and mypy
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy

DEMO := LVM_DATA_DIR=data/demo LVM_RAW_URI=

demo: ## Whole pipeline on the bundled sample data: no download, under a minute
	@mkdir -p data/demo
	$(DEMO) $(BIN)/lvm sample
	$(DEMO) $(DBT) build $(DBT_FLAGS) --vars '{min_vehicles_per_model: 2}'
	$(DEMO) $(BIN)/lvm export
	@echo "Open it with:  LVM_DATA_DIR=data/demo make dashboard"

unit: ## dbt unit tests, run on the sample data (builds only what they need)
	@mkdir -p data/demo
	$(DEMO) $(BIN)/lvm sample
	$(DEMO) $(DBT) build $(DBT_FLAGS) --select "+test_type:unit" --exclude "test_type:data"

figures: ## Regenerate the README charts and docs/findings.md from the marts
	$(BIN)/python scripts/build_report.py

snapshot: ## Refresh the marts snapshot the dashboard falls back to
	cp data/export/*.parquet dashboard/snapshot/

format: ## Auto-format
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

docs: ## Build and serve dbt docs with lineage
	@mkdir -p data
	$(DBT) docs generate $(DBT_FLAGS)
	$(DBT) docs serve $(DBT_FLAGS)

clean: ## Remove build artefacts (keeps raw data)
	rm -rf dbt/target dbt/logs data/warehouse.duckdb data/export .pytest_cache .ruff_cache
