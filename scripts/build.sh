#!/usr/bin/env bash
# TurboAPI build script — builds and installs the Zig turbonet extension.
# Usage:
#   ./scripts/build.sh              # debug build + install
#   ./scripts/build.sh --release    # release build + install
#   ./scripts/build.sh --check      # compile only, no install (for pre-commit)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIG_DIR="$ROOT/zig"

# Detect Python — prefer venv, fall back to system
if [ -n "${VIRTUAL_ENV:-}" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -x "$ROOT/.venv314t/bin/python" ]; then
    PYTHON="$ROOT/.venv314t/bin/python"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

MODE=""
CHECK_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --release) MODE="--release" ;;
        --check)   CHECK_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--release] [--check]"
            echo "  --release  Build with ReleaseFast optimizations"
            echo "  --check    Compile-only (no install), for pre-commit validation"
            exit 0
            ;;
    esac
done

echo "⚡ TurboAPI build"
echo "   Python: $PYTHON"
echo "   Zig dir: $ZIG_DIR"

if $CHECK_ONLY; then
    echo "   Mode: compile check (no install)"
    "$PYTHON" "$ZIG_DIR/build_turbonet.py" $MODE
else
    echo "   Mode: build + install"
    "$PYTHON" "$ZIG_DIR/build_turbonet.py" --install $MODE
fi

echo ""
echo "✅ Build complete"
