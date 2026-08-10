.PHONY: install dev watch start test lint format

UV_CACHE_DIR ?= $(CURDIR)/.ci-agent/uv-cache
export UV_CACHE_DIR

install:
	uv sync --locked

dev:
	PYTHONDONTWRITEBYTECODE=1 uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001

watch:
	PYTHONDONTWRITEBYTECODE=1 uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

start:
	PYTHONDONTWRITEBYTECODE=1 uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001

test:
	uv run pytest

lint:
	uv run ruff check app packages/competition/competition tests
	uv run ruff format --check app packages/competition/competition tests

format:
	uv run ruff check --fix app packages/competition/competition tests
	uv run ruff format app packages/competition/competition tests
