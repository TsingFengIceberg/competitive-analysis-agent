#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-dev}"
if [[ "$MODE" != "dev" && "$MODE" != "watch" && "$MODE" != "start" ]]; then
    echo "Usage: $0 [dev|watch|start]" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.ci-agent/run"
RUNNER_PID_FILE="$RUN_DIR/runner.pid"

export UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.ci-agent/uv-cache}"

mkdir -p "$RUN_DIR"

if [[ -f "$RUNNER_PID_FILE" ]]; then
    EXISTING_PID="$(cat "$RUNNER_PID_FILE")"
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Services are already running (PID $EXISTING_PID)." >&2
        exit 1
    fi
    rm -f "$RUNNER_PID_FILE"
fi

if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-2026}"
export CA_AGENT_API_BASE_URL="${CA_AGENT_API_BASE_URL:-http://127.0.0.1:$BACKEND_PORT}"

if [[ "$MODE" == "dev" ]]; then
    "$REPO_ROOT/scripts/build-frontend.sh"
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    trap - EXIT INT TERM
    [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
    [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "$FRONTEND_PID" ]] && wait "$FRONTEND_PID" 2>/dev/null || true
    [[ -n "$BACKEND_PID" ]] && wait "$BACKEND_PID" 2>/dev/null || true
    rm -f "$RUNNER_PID_FILE"
}
trap cleanup EXIT INT TERM

echo "$$" > "$RUNNER_PID_FILE"

(
    cd "$REPO_ROOT/backend"
    export PYTHONDONTWRITEBYTECODE=1
    if [[ "$MODE" == "watch" ]]; then
        exec uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
    fi
    exec uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

(
    cd "$REPO_ROOT/frontend"
    if command -v pnpm >/dev/null 2>&1; then
        if [[ "$MODE" == "watch" ]]; then
            exec pnpm dev --hostname 0.0.0.0 --port "$FRONTEND_PORT"
        fi
        if [[ ! -f .next/BUILD_ID && ! -f .next/server/app-paths-manifest.json ]]; then
            echo "Frontend build missing. Run 'make build' before 'make start'." >&2
            exit 1
        fi
        exec pnpm start --hostname 0.0.0.0 --port "$FRONTEND_PORT"
    fi

    NEXT_BIN="$REPO_ROOT/frontend/node_modules/.bin/next"
    if [[ ! -x "$NEXT_BIN" ]]; then
        echo "pnpm is unavailable and the installed Next.js binary was not found. Run 'make install' first." >&2
        exit 1
    fi
    echo "pnpm is unavailable; using the installed Next.js binary."
    if [[ "$MODE" == "watch" ]]; then
        exec "$NEXT_BIN" dev --turbo --hostname 0.0.0.0 --port "$FRONTEND_PORT"
    fi
    if [[ ! -f .next/BUILD_ID && ! -f .next/server/app-paths-manifest.json ]]; then
        echo "Frontend build missing. Run 'make build' before 'make start'." >&2
        exit 1
    fi
    exec "$NEXT_BIN" start --hostname 0.0.0.0 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "Backend: http://localhost:$BACKEND_PORT"
echo "Frontend: http://localhost:$FRONTEND_PORT/competition"
[[ "$MODE" == "watch" ]] && echo "Warning: watch mode performs substantially more disk I/O."
echo "Press Ctrl+C to stop both services."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_CODE=$?
echo "A service exited with status $EXIT_CODE; stopping the other service." >&2
exit "$EXIT_CODE"
