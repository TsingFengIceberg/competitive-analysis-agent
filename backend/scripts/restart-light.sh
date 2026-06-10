#!/usr/bin/env bash
#
# restart-light.sh — Low-IO restart for competition development
#
set -eo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

"$REPO_ROOT/scripts/cleanup-all.sh"
echo ""

FORCE_BUILD=false
DO_BACKEND=true
DO_FRONTEND=true

for arg in "$@"; do
    case "$arg" in
        --backend)  DO_FRONTEND=false ;;
        --frontend) DO_BACKEND=false ;;
        --force-build) FORCE_BUILD=true ;;
        *) echo "Unknown: $arg"; exit 1 ;;
    esac
done

NEED_BUILD=false
BUILD_STAMP="$REPO_ROOT/frontend/.next/BUILD_ID"

if $DO_FRONTEND; then
    if $FORCE_BUILD; then
        NEED_BUILD=true
        echo "Force rebuild requested"
    elif [ ! -f "$BUILD_STAMP" ]; then
        NEED_BUILD=true
        echo "No previous build found"
    else
        LAST_BUILD=$(stat -c %Y "$BUILD_STAMP" 2>/dev/null)
        if [ -z "$LAST_BUILD" ]; then
            NEED_BUILD=true
        else
            CHANGED=$(find "$REPO_ROOT/frontend/src" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.css" -o -name "*.js" \) -newer "$BUILD_STAMP" 2>/dev/null | wc -l)
            if [ "$CHANGED" -gt 0 ]; then
                NEED_BUILD=true
                echo "$CHANGED frontend source file(s) changed since last build"
            else
                echo "Frontend sources unchanged - skipping rebuild"
            fi
        fi
    fi
fi

if $DO_BACKEND; then
    echo "Starting backend gateway (port 8001)..."
    cd "$REPO_ROOT/backend"
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPYCACHEPREFIX=/dev/shm/pycache \
    PYTHONPATH=packages/competition \
    nohup uv run uvicorn app.main:app \
        --host 0.0.0.0 --port 8001 \
        --log-level warning \
        > /tmp/gateway.log 2>&1 &

    for i in $(seq 1 10); do
        sleep 1
        if fuser 8001/tcp >/dev/null 2>&1; then
            break
        fi
    done

    if fuser 8001/tcp >/dev/null 2>&1; then
        echo "Gateway started"
    else
        echo "Gateway failed - check /tmp/gateway.log"
        tail -10 /tmp/gateway.log
        exit 1
    fi
fi

if $DO_FRONTEND && $NEED_BUILD; then
    echo "Building frontend..."
    cd "$REPO_ROOT/frontend"
    PYTHONDONTWRITEBYTECODE=1 eatmydata ionice -c 2 -n 7 nice -n 10 \
        env NEXT_PUBLIC_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" pnpm build 2>&1 | tail -20
    echo "Build complete"
fi

if $DO_FRONTEND; then
    echo "Starting frontend (port 3000)..."
    cd "$REPO_ROOT/frontend"
    PORT=3000 nohup pnpm start > /tmp/frontend.log 2>&1 &
    sleep 2
    if fuser 3000/tcp >/dev/null 2>&1; then
        echo "Frontend started"
        nginx 2>/dev/null || nginx -s reload 2>/dev/null || true
    else
        echo "Frontend failed - check /tmp/frontend.log"
        tail -10 /tmp/frontend.log
        exit 1
    fi
fi

echo ""
echo "======= Services ======="
fuser 8001/tcp >/dev/null 2>&1 && echo "  Gateway :8001 OK" || echo "  Gateway :8001 DOWN"
fuser 3000/tcp >/dev/null 2>&1 && echo "  Next.js :3000 OK" || echo "  Next.js :3000 DOWN"
fuser 2026/tcp >/dev/null 2>&1 && echo "  nginx   :2026 OK" || echo "  nginx   :2026 DOWN"
echo "  Competition: http://localhost:2026/competition"
