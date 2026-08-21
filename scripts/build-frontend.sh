#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_ROOT="$REPO_ROOT/frontend"
BUILD_ID="$FRONTEND_ROOT/.next/BUILD_ID"
FORCE_BUILD=false

if [[ "${1:-}" == "--force" ]]; then
    FORCE_BUILD=true
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 2
fi

needs_build="$FORCE_BUILD"
if [[ ! -f "$BUILD_ID" ]]; then
    needs_build=true
elif [[ "$needs_build" == false ]]; then
    changed_source="$(
        find "$FRONTEND_ROOT/src" "$FRONTEND_ROOT/public" \
            -type f -newer "$BUILD_ID" -print -quit 2>/dev/null
    )"
    if [[ -n "$changed_source" ]]; then
        needs_build=true
    fi

    for config_file in \
        package.json pnpm-lock.yaml next.config.js postcss.config.mjs tsconfig.json; do
        if [[ "$FRONTEND_ROOT/$config_file" -nt "$BUILD_ID" ]]; then
            needs_build=true
            break
        fi
    done
fi

if [[ "$needs_build" == false ]]; then
    echo "Frontend sources are unchanged; reusing the existing production build."
    exit 0
fi

echo "Building the frontend at idle I/O and low CPU priority..."
if command -v pnpm >/dev/null 2>&1; then
    build_command=(pnpm build)
elif [[ -x "$FRONTEND_ROOT/node_modules/.bin/next" ]]; then
    echo "pnpm is unavailable; using the installed Next.js binary."
    # Next 16's default Turbopack build may require an internal port for CSS
    # processing in restricted environments; Webpack produces the same
    # production artifact without that requirement.
    build_command=("$FRONTEND_ROOT/node_modules/.bin/next" build --webpack)
else
    echo "Neither pnpm nor frontend/node_modules/.bin/next is available. Run 'make install' first." >&2
    exit 1
fi
if command -v eatmydata >/dev/null 2>&1; then
    build_command=(eatmydata "${build_command[@]}")
fi
if command -v ionice >/dev/null 2>&1; then
    build_command=(ionice -c 3 "${build_command[@]}")
fi
if command -v nice >/dev/null 2>&1; then
    build_command=(nice -n 15 "${build_command[@]}")
fi

cd "$FRONTEND_ROOT"
NEXT_TELEMETRY_DISABLED=1 "${build_command[@]}"
