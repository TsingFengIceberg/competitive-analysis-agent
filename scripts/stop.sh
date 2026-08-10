#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_PID_FILE="$REPO_ROOT/.ci-agent/run/runner.pid"

if [[ ! -f "$RUNNER_PID_FILE" ]]; then
    echo "No repository-managed services are running."
    exit 0
fi

RUNNER_PID="$(cat "$RUNNER_PID_FILE")"
if ! kill -0 "$RUNNER_PID" 2>/dev/null; then
    rm -f "$RUNNER_PID_FILE"
    echo "Removed a stale PID file."
    exit 0
fi

COMMAND="$(ps -p "$RUNNER_PID" -o args= 2>/dev/null || true)"
if [[ "$COMMAND" != *"scripts/run.sh"* ]]; then
    echo "PID $RUNNER_PID is not the repository runner; refusing to stop it." >&2
    exit 1
fi

kill "$RUNNER_PID"
for _ in {1..50}; do
    kill -0 "$RUNNER_PID" 2>/dev/null || break
    sleep 0.1
done
rm -f "$RUNNER_PID_FILE"
echo "Services stopped."
