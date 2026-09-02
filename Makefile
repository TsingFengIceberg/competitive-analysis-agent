.PHONY: help install dev watch start stop restart clean test rag-eval rag-experiments lint format typecheck build

UV_CACHE_DIR ?= $(CURDIR)/.ci-agent/uv-cache
export UV_CACHE_DIR

help:
	@echo "Competitive Analysis Agent"
	@echo "  make install    Install Python and frontend dependencies"
	@echo "  make dev        Run the low-I/O development stack"
	@echo "  make watch      Run both services with hot reload (high I/O)"
	@echo "  make start      Run FastAPI and a pre-built Next.js app"
	@echo "  make stop       Stop services started by this repository"
	@echo "  make restart    Restart in development mode"
	@echo "  make test       Run backend and frontend tests"
	@echo "  make rag-eval   Run the versioned local RAG golden-set evaluation"
	@echo "  make rag-experiments   Run the RAG ablation matrix and report deltas"
	@echo "  make lint       Run Python and frontend linters"
	@echo "  make typecheck  Run the frontend TypeScript checker"
	@echo "  make build      Build the frontend"

install:
	cd backend && uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

dev:
	./scripts/run.sh dev

watch:
	./scripts/run.sh watch

start:
	./scripts/run.sh start

stop:
	./scripts/stop.sh

restart:
	./scripts/stop.sh
	./scripts/run.sh dev

clean:
	rm -rf .ci-agent/run frontend/.next

test:
	cd backend && uv run pytest
	cd frontend && pnpm test

rag-eval:
	cd backend && uv run --locked python ../scripts/evaluate-rag.py --strict

rag-experiments:
	cd backend && uv run --locked python ../scripts/run-rag-experiments.py --strict

lint:
	cd backend && uv run ruff check app packages/competition/competition tests
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff check --fix app packages/competition/competition tests
	cd backend && uv run ruff format app packages/competition/competition tests
	cd frontend && pnpm format:write

typecheck:
	cd frontend && pnpm typecheck

build:
	./scripts/build-frontend.sh --force
