.PHONY: help install start stop restart clean test lint build docker docker-stop

help:
	@echo "Competitive-Analysis-Agent Commands:"
	@echo "  make install       - Install all dependencies"
	@echo "  make start         - Start production services"
	@echo "  make stop          - Stop all services"
	@echo "  make restart       - Restart all services"
	@echo "  make clean         - Clean up processes and temp files"
	@echo "  make test          - Run backend tests"
	@echo "  make lint          - Run all linters"
	@echo "  make build         - Build frontend for production"
	@echo "  make docker        - Start via Docker Compose"
	@echo "  make docker-stop   - Stop Docker Compose"

install:
	@echo "Installing backend dependencies..."
	cd backend && uv sync
	@echo "Installing frontend dependencies..."
	cd frontend && pnpm install
	@echo "Done."

start:
	./scripts/restart-light.sh

stop:
	./scripts/cleanup-all.sh

restart:
	./scripts/restart-light.sh

clean:
	./scripts/cleanup-all.sh

build:
	cd frontend && pnpm build

docker:
	docker compose -f docker/docker-compose.yaml up -d

docker-stop:
	docker compose -f docker/docker-compose.yaml down

test:
	cd backend && PYTHONPATH=packages/competition uv run pytest tests/test_competition_*.py tests/test_branchtree*.py tests/test_checkpoint_ops.py tests/test_conversation_tree.py -v

lint:
	cd backend && uv run ruff check packages/competition/competition/ tests/
	cd frontend && pnpm lint
