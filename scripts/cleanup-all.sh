#!/usr/bin/env bash
#
# cleanup-all.sh — Thorough process and resource cleanup
#
# Kills ALL project-related processes (uvicorn, node/next, pnpm, orphaned children),
# frees ports 8001/3000/2026, cleans tmpfs build artifacts and Python caches.
#
# Usage:
#   ./scripts/cleanup-all.sh              # full cleanup
#   ./scripts/cleanup-all.sh --dry-run    # show what would be killed (no action)
#
set -e

DRY_RUN=false
[[ "$1" == "--dry-run" ]] && DRY_RUN=true

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"

_kill() {
    local sig="${2:--9}"
    if $DRY_RUN; then
        echo "  [DRY-RUN] Would kill: $1"
        return
    fi
    kill "$sig" "$1" 2>/dev/null || true
}

_kill_port() {
    local pid
    pid=$(fuser "$1"/tcp 2>/dev/null) || true
    if [ -n "$pid" ]; then
        echo "  Killing PID $pid on port $1..."
        _kill "$pid"
        sleep 0.3
    fi
}

step() { echo "→ $1"; }
done_step() { echo "  ✓ done"; }

echo "====== Cleanup $(date +%H:%M:%S) ======"
if $DRY_RUN; then
    echo "[DRY-RUN MODE — no processes will be killed]"
fi

# 1. Kill project services by port
step "Freeing ports 8001 (gateway), 3000 (next dev), 2026 (nginx)..."
_kill_port 8001
_kill_port 3000
_kill_port 2026
done_step

# 2. Kill pnpm/node processes spawned from this project
#    Target: pnpm dev, pnpm start, pnpm build, next-server, next build
step "Killing pnpm/node processes under $REPO_ROOT..."
for pattern in \
    "pnpm.*$REPO_ROOT" \
    "next-server.*$REPO_ROOT" \
    "next.*build.*$REPO_ROOT" \
    "uvicorn.*app.gateway" \
    "node.*$REPO_ROOT/frontend" \
    "turbopack" \
    "node.*\.next" \
    "pnpm.*node_modules" \
    ; do
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    for pid in $pids; do
        # Never kill VSCode or nginx master in these patterns
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "")
        if echo "$cmdline" | grep -qE "vscode-server|nginx: master"; then
            continue
        fi
        echo "  Killing PID $pid: ${cmdline:0:120}..."
        _kill "$pid"
        # Wait briefly and escalate to SIGKILL if still alive
        sleep 0.2
        if ! $DRY_RUN && kill -0 "$pid" 2>/dev/null; then
            _kill "$pid" -9
        fi
    done
done
done_step

# 3. Kill any remaining processes on our ports (belt-and-suspenders)
step "Double-checking ports..."
for port in 8001 3000 2026; do
    if fuser "$port"/tcp 2>/dev/null; then
        echo "  Port $port still occupied — force killing..."
        fuser -k "$port"/tcp 2>/dev/null || true
    fi
done
done_step

# 4. Clean tmpfs build artifacts
step "Cleaning tmpfs build artifacts..."
if ! $DRY_RUN; then
    rm -rf /tmp/next-build-* 2>/dev/null || true
    rm -rf /tmp/.next* 2>/dev/null || true
    rm -f /tmp/gateway.log /tmp/frontend.log 2>/dev/null || true
fi
done_step

# 5. Clean Python bytecode caches (in case PYTHONDONTWRITEBYTECODE was off)
step "Cleaning Python bytecode caches..."
if ! $DRY_RUN; then
    find "$REPO_ROOT/backend" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find "$REPO_ROOT/backend" -name "*.pyc" -delete 2>/dev/null || true
    rm -rf /dev/shm/pycache 2>/dev/null || true
fi
done_step

# 6. Verify clean state
step "Verifying..."
for port in 8001 3000 2026; do
    if fuser "$port"/tcp 2>/dev/null; then
        echo "  ⚠ Port $port STILL occupied!"
    else
        echo "  Port $port: free"
    fi
done

if ! $DRY_RUN; then
    remaining=$(ps aux | grep -E "(uvicorn|pnpm.*build|next-server|turbopack)" | grep -v grep | grep -v vscode | wc -l)
    if [ "$remaining" -gt 0 ]; then
        echo "  ⚠ $remaining suspicious process(es) remaining:"
        ps aux | grep -E "(uvicorn|pnpm.*build|next-server|turbopack)" | grep -v grep | grep -v vscode
    else
        echo "  No orphaned processes found"
    fi

    # Check IO pressure
    if command -v iostat &>/dev/null; then
        iowait=$(iostat -x 1 2 | tail -1 | awk '{print $4}' 2>/dev/null || echo "N/A")
        echo "  IO wait: ${iowait}%"
    fi

    # Show memory
    mem_free=$(free -h | awk '/^Mem:/ {print $4}')
    echo "  Memory free: $mem_free"
fi

echo ""
echo "====== Cleanup complete ======"
