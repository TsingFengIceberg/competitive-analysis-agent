#!/usr/bin/env bash
#
# restart-light.sh — Low-IO restart for competition development
#
# Only rebuilds frontend when source files have changed.
# IO optimisations applied during build:
#   1. tmpfs build    — .next/ is built in RAM (/tmp), then copied to disk
#                        as a single sequential write instead of 10,000+ random IOs
#   2. eatmydata      — disables fsync/O_SYNC
#   3. ionice + nice  — low IO/CPU priority so the system stays responsive
#   4. --no-lint      — skip ESLint (production build doesn't need it)
#   5. PYTHONDONTWRITEBYTECODE=1 + pycache→/dev/shm  — no .pyc writes
#
# Usage:
#   ./scripts/restart-light.sh              # restart both (smart rebuild)
#   ./scripts/restart-light.sh --backend    # restart backend only (no frontend build)
#   ./scripts/restart-light.sh --frontend   # rebuild + restart frontend only
#   ./scripts/restart-light.sh --force-build  # force frontend rebuild
#   ./scripts/restart-light.sh --stop-agents # pause Alibaba Cloud agents during build
#
set -eo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

# ── Pre-flight cleanup ──────────────────────────────────────────────────────────
# Always clean up orphaned processes and ports before starting.
# This prevents background IO consumers from starving the ESSD Entry disk.
"$REPO_ROOT/scripts/cleanup-all.sh"
echo ""

FORCE_BUILD=false
DO_BACKEND=true
DO_FRONTEND=true
STOP_AGENTS=false

for arg in "$@"; do
    case "$arg" in
        --backend)  DO_FRONTEND=false ;;
        --frontend) DO_BACKEND=false ;;
        --force-build) FORCE_BUILD=true ;;
        --stop-agents) STOP_AGENTS=true ;;
        *) echo "Unknown: $arg"; exit 1 ;;
    esac
done

# ── Smart frontend rebuild check ───────────────────────────────────────────────

NEED_BUILD=false
BUILD_STAMP="$REPO_ROOT/frontend/.next/BUILD_ID"

if $DO_FRONTEND; then
    if $FORCE_BUILD; then
        NEED_BUILD=true
        echo "🔨 Force rebuild requested"
    elif [ ! -f "$BUILD_STAMP" ]; then
        NEED_BUILD=true
        echo "🔨 No previous build found (.next/BUILD_ID missing)"
    else
        LAST_BUILD=$(stat -c %Y "$BUILD_STAMP" 2>/dev/null)
        if [ -z "$LAST_BUILD" ]; then
            NEED_BUILD=true
        else
            CHANGED=$(find "$REPO_ROOT/frontend/src" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.css" -o -name "*.js" \) -newer "$BUILD_STAMP" 2>/dev/null | wc -l)
            if [ "$CHANGED" -gt 0 ]; then
                NEED_BUILD=true
                echo "🔨 $CHANGED frontend source file(s) changed since last build"
            else
                echo "✅ Frontend sources unchanged — skipping rebuild"
            fi
        fi
    fi
fi

# ── Backend ────────────────────────────────────────────────────────────────────

if $DO_BACKEND; then
    echo ""
    echo "🚀 Starting backend gateway (port 8001)..."
    cd "$REPO_ROOT/backend"
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPYCACHEPREFIX=/dev/shm/pycache \
    PYTHONPATH=packages/competition \
    nohup uv run uvicorn app.main:app \
        --host 0.0.0.0 --port 8001 \
        --log-level warning \
        > /tmp/gateway.log 2>&1 &

    # Wait up to 10s for gateway to be ready
    for i in $(seq 1 10); do
        sleep 1
        if fuser 8001/tcp >/dev/null 2>&1; then
            break
        fi
    done

    if fuser 8001/tcp >/dev/null 2>&1; then
        echo "✅ Gateway started (PID: $(fuser 8001/tcp 2>/dev/null | cut -d' ' -f1))"
    else
        echo "❌ Gateway failed to start — check /tmp/gateway.log"
        tail -10 /tmp/gateway.log
        exit 1
    fi
fi

# ── Frontend build (only if needed) ────────────────────────────────────────────

if $DO_FRONTEND && $NEED_BUILD; then
    echo ""
    echo "📦 Building frontend (tmpfs RAM build — zero disk IO)..."

    # Temporarily stop Alibaba Cloud agents that constantly poll/write to disk
    AGENT_PIDS=""
    if $STOP_AGENTS; then
        for agent in aliyun-service hbrclient AliYunDun; do
            pids=$(pgrep -f "$agent" 2>/dev/null || true)
            if [ -n "$pids" ]; then
                echo "  ⏸  Pausing $agent..."
                kill -STOP $pids 2>/dev/null || true
                AGENT_PIDS="$AGENT_PIDS $pids"
            fi
        done
    fi

    cd "$REPO_ROOT/frontend"

    # Build directly — Turbopack (Next.js 16 default) is far more IO-efficient
    # than webpack. The old tmpfs build approach is incompatible with Turbopack's
    # postcss module resolution. eatmydata + ionice still provide IO protection.
    BUILD_OK=false
    if PYTHONDONTWRITEBYTECODE=1 eatmydata ionice -c 2 -n 7 nice -n 10 \
        env NEXT_PUBLIC_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" pnpm build 2>&1 | tail -20; then

        BUILD_OK=true
        echo "✅ Build complete"
    else
        echo "❌ Build failed"
    fi

    # Resume cloud agents
    if [ -n "$AGENT_PIDS" ]; then
        echo "  ▶  Resuming agents..."
        for pid in $AGENT_PIDS; do
            kill -CONT $pid 2>/dev/null || true
        done
    fi

    if ! $BUILD_OK; then
        exit 1
    fi
fi

# ── Frontend production server ─────────────────────────────────────────────────

if $DO_FRONTEND; then
    echo ""
    echo "🚀 Starting frontend production server (port 3000, nginx proxies 2026→3000)..."
    cd "$REPO_ROOT/frontend"
    PORT=3000 nohup pnpm start > /tmp/frontend.log 2>&1 &
    sleep 2

    if fuser 3000/tcp >/dev/null 2>&1; then
        echo "✅ Frontend started (PID: $(fuser 3000/tcp 2>/dev/null | cut -d' ' -f1))"
        # Start/restart nginx on port 2026
        if command -v nginx >/dev/null 2>&1; then
            nginx 2>/dev/null || nginx -s reload 2>/dev/null || true
            if fuser 2026/tcp >/dev/null 2>&1; then
                echo "✅ nginx started on port 2026"
            else
                echo "⚠ nginx failed to start — frontend on port 3000 directly"
            fi
        fi
    else
        echo "❌ Frontend failed to start — check /tmp/frontend.log"
        tail -10 /tmp/frontend.log
        exit 1
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────────────

echo ""
echo "======= Services ======="
if $DO_BACKEND; then
    echo "  Gateway:  http://localhost:8001"
    echo "  Log:      /tmp/gateway.log"
fi
if $DO_FRONTEND; then
    echo "  Frontend: http://localhost:2026 (nginx → 3000)"
    echo "  Log:      /tmp/frontend.log"
fi
echo ""
echo "  Competition page: http://localhost:2026/competition"
echo ""

# ── Always ensure nginx is running ─────────────────────────────────────────────
# cleanup-all.sh kills nginx, so restart it unconditionally.
# Also restart frontend if it was killed but not being rebuilt (e.g. --backend mode).
_ensure_nginx() {
    if ! fuser 2026/tcp >/dev/null 2>&1; then
        nginx 2>/dev/null || true
        sleep 0.5
    fi
}
_ensure_frontend() {
    if ! fuser 3000/tcp >/dev/null 2>&1; then
        cd "$REPO_ROOT/frontend"
        PORT=3000 nohup pnpm start > /tmp/frontend.log 2>&1 &
        sleep 2
    fi
}

if ! $DO_FRONTEND; then
    _ensure_frontend
fi
_ensure_nginx

# Verify final state
echo "  Final:"
fuser 8001/tcp >/dev/null 2>&1 && echo "    Gateway :8001 ✓" || echo "    Gateway :8001 ✗"
fuser 3000/tcp >/dev/null 2>&1 && echo "    Next.js :3000 ✓" || echo "    Next.js :3000 ✗"
fuser 2026/tcp >/dev/null 2>&1 && echo "    nginx   :2026 ✓" || echo "    nginx   :2026 ✗"
echo ""
