#!/usr/bin/env bash
#
# dev-instance.sh — 在独立端口上启动/停止调试实例
#
# 与生产实例（8001/3000/2026）完全隔离，用于开发调试。
# 评委访问 http://<IP>:2026/competition 不受影响。
#
# 端口规划:
#   生产: Gateway :8001  Frontend :3000  Nginx :2026
#   调试: Gateway :8002  Frontend :3001  Nginx :2027
#
# Usage:
#   ./scripts/dev-instance.sh start              # 启动完整调试栈
#   ./scripts/dev-instance.sh start --backend    # 仅启动后端
#   ./scripts/dev-instance.sh start --frontend   # 仅启动前端 + nginx
#   ./scripts/dev-instance.sh stop               # 停止所有调试端口
#   ./scripts/dev-instance.sh status             # 查看端口状态
#
set -eo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

# ── Port definitions ──
PROD_BACKEND=8001
PROD_FRONTEND=3000
PROD_NGINX=2026

DEV_BACKEND=8002
DEV_FRONTEND=3001
DEV_NGINX=2027

NGINX_DEV_CONF="$REPO_ROOT/docker/nginx/nginx.dev.conf"

# ── Helpers ──

_port_pid() { fuser "$1"/tcp 2>/dev/null | cut -d' ' -f1; }

_port_status() {
    local pid
    pid=$(_port_pid "$1")
    if [ -n "$pid" ]; then
        echo "  :$1 → PID $pid ✓"
    else
        echo "  :$1 — free ✗"
    fi
}

_kill_port() {
    local pid
    pid=$(_port_pid "$1")
    if [ -n "$pid" ]; then
        echo "  Killing PID $pid on port $1..."
        kill "$pid" 2>/dev/null || true
        sleep 0.3
        # Force if still alive
        if fuser "$1"/tcp >/dev/null 2>&1; then
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "  Port $1 freed"
    else
        echo "  Port $1 already free"
    fi
}

_ensure_free() {
    if fuser "$1"/tcp >/dev/null 2>&1; then
        echo "❌ Port $1 is occupied — run './scripts/dev-instance.sh stop' first"
        exit 1
    fi
}

# ── Status ──

do_status() {
    echo "======= Port Status ======="
    echo "Production:"
    _port_status $PROD_BACKEND
    _port_status $PROD_FRONTEND
    _port_status $PROD_NGINX
    echo ""
    echo "Dev:"
    _port_status $DEV_BACKEND
    _port_status $DEV_FRONTEND
    _port_status $DEV_NGINX
    echo ""
}

# ── Stop ──

do_stop() {
    echo "======= Stopping Dev Instance ======="
    echo "→ Freeing dev ports ($DEV_NGINX, $DEV_FRONTEND, $DEV_BACKEND)..."
    _kill_port $DEV_NGINX
    _kill_port $DEV_FRONTEND
    _kill_port $DEV_BACKEND

    # Kill any orphaned uvicorn/node for dev ports
    for pattern in "uvicorn.*app.main.*$DEV_BACKEND" "next-server.*$DEV_FRONTEND"; do
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        for pid in $pids; do
            cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "")
            if echo "$cmdline" | grep -qE "vscode-server"; then continue; fi
            echo "  Killing orphan PID $pid: ${cmdline:0:120}..."
            kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        done
    done

    echo "======= Dev Instance Stopped ======="
    echo ""
    do_status
}

# ── Start ──

do_start() {
    local DO_BACKEND=true
    local DO_FRONTEND=true
    local FORCE_BUILD=false

    for arg in "$@"; do
        case "$arg" in
            --backend) DO_FRONTEND=false ;;
            --frontend) DO_BACKEND=false ;;
            --force-build) FORCE_BUILD=true ;;
            *) echo "Unknown: $arg"; exit 1 ;;
        esac
    done

    # Check dev ports are free
    if $DO_BACKEND; then
        _ensure_free $DEV_BACKEND
    fi
    if $DO_FRONTEND; then
        _ensure_free $DEV_FRONTEND
        _ensure_free $DEV_NGINX
    fi

    # ── Backend ──
    if $DO_BACKEND; then
        echo ""
        echo "🚀 Starting DEV backend gateway (port $DEV_BACKEND)..."
        cd "$REPO_ROOT/backend"

        if [ -f "$REPO_ROOT/.env" ]; then
            set -a; source "$REPO_ROOT/.env"; set +a
        fi

        PYTHONDONTWRITEBYTECODE=1 \
        PYTHONPYCACHEPREFIX=/dev/shm/pycache \
        PYTHONPATH=packages/competition \
        nohup uv run uvicorn app.main:app \
            --host 0.0.0.0 --port $DEV_BACKEND \
            --log-level warning \
            > /tmp/gateway-dev.log 2>&1 &

        for i in $(seq 1 10); do
            sleep 1
            if fuser $DEV_BACKEND/tcp >/dev/null 2>&1; then break; fi
        done

        if fuser $DEV_BACKEND/tcp >/dev/null 2>&1; then
            echo "✅ Dev gateway started :$DEV_BACKEND (PID: $(_port_pid $DEV_BACKEND))"
        else
            echo "❌ Dev gateway failed to start — check /tmp/gateway-dev.log"
            tail -10 /tmp/gateway-dev.log
            exit 1
        fi
    fi

    # ── Frontend build check ──
    NEED_BUILD=false
    BUILD_STAMP="$REPO_ROOT/frontend/.next/BUILD_ID"

    if $DO_FRONTEND; then
        if $FORCE_BUILD; then
            NEED_BUILD=true
            echo "🔨 Force rebuild requested"
        elif [ ! -f "$BUILD_STAMP" ]; then
            NEED_BUILD=true
            echo "🔨 No previous build found"
        else
            LAST_BUILD=$(stat -c %Y "$BUILD_STAMP" 2>/dev/null)
            CHANGED=$(find "$REPO_ROOT/frontend/src" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.css" -o -name "*.js" \) -newer "$BUILD_STAMP" 2>/dev/null | wc -l)
            if [ "$CHANGED" -gt 0 ]; then
                NEED_BUILD=true
                echo "🔨 $CHANGED frontend source file(s) changed"
            else
                echo "✅ Frontend sources unchanged — sharing prod build"
            fi
        fi
    fi

    if $DO_FRONTEND && $NEED_BUILD; then
        echo ""
        echo "📦 Building frontend (low IO priority)..."
        cd "$REPO_ROOT/frontend"
        if PYTHONDONTWRITEBYTECODE=1 eatmydata ionice -c 2 -n 7 nice -n 10 \
            env NEXT_PUBLIC_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" pnpm build 2>&1 | tail -20; then
            echo "✅ Build complete"
        else
            echo "❌ Build failed"
            exit 1
        fi
    fi

    # ── Frontend ──
    if $DO_FRONTEND; then
        echo ""
        echo "🚀 Starting DEV frontend server (port $DEV_FRONTEND)..."
        cd "$REPO_ROOT/frontend"
        PORT=$DEV_FRONTEND nohup pnpm start > /tmp/frontend-dev.log 2>&1 &
        sleep 2

        if fuser $DEV_FRONTEND/tcp >/dev/null 2>&1; then
            echo "✅ Dev frontend started :$DEV_FRONTEND (PID: $(_port_pid $DEV_FRONTEND))"
        else
            echo "❌ Dev frontend failed to start — check /tmp/frontend-dev.log"
            tail -10 /tmp/frontend-dev.log
            exit 1
        fi

        # ── Nginx ──
        echo ""
        echo "🚀 Starting DEV nginx (port $DEV_NGINX → $DEV_BACKEND/$DEV_FRONTEND)..."
        if [ ! -f "$NGINX_DEV_CONF" ]; then
            echo "❌ Dev nginx config not found at $NGINX_DEV_CONF"
            exit 1
        fi
        nginx -c "$NGINX_DEV_CONF" 2>/dev/null || nginx -c "$NGINX_DEV_CONF" -s reload 2>/dev/null || true
        sleep 0.5

        if fuser $DEV_NGINX/tcp >/dev/null 2>&1; then
            echo "✅ Dev nginx started :$DEV_NGINX"
        else
            echo "⚠ Dev nginx failed to start — frontend on :$DEV_FRONTEND directly"
        fi
    fi

    # ── Summary ──
    echo ""
    echo "======= Dev Instance ======="
    if $DO_BACKEND; then
        echo "  Gateway:  http://localhost:$DEV_BACKEND"
        echo "  Log:      /tmp/gateway-dev.log"
    fi
    if $DO_FRONTEND; then
        echo "  Frontend: http://localhost:$DEV_FRONTEND"
        echo "  Nginx:    http://localhost:$DEV_NGINX"
        echo "  Log:      /tmp/frontend-dev.log"
    fi
    echo ""
    echo "  Dev page: http://localhost:$DEV_NGINX/competition"
    echo ""
}

# ── Main ──

case "${1:-}" in
    start)
        shift
        do_start "$@"
        ;;
    stop)
        do_stop
        ;;
    status)
        do_status
        ;;
    *)
        echo "Usage: $0 {start|stop|status} [--backend|--frontend] [--force-build]"
        echo ""
        echo "  start           启动完整调试栈（:8002 + :3001 + :2027）"
        echo "  start --backend  仅启动后端 :8002"
        echo "  start --frontend 仅启动前端 :3001 + nginx :2027"
        echo "  start --force-build  强制重新构建前端"
        echo "  stop            停止所有调试端口"
        echo "  status          查看端口状态"
        echo ""
        echo "  生产端口 (:8001 :3000 :2026) 不受影响"
        exit 1
        ;;
esac
