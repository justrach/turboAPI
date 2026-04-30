#!/usr/bin/env bash
# Build the io_uring smoke-test binary for Linux (aarch64-linux-musl by
# default; override with TARGET=...). Designed to run on macOS via Apple
# `container`, on a Linux dev box natively, or in CI on a Linux runner.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

TARGET="${TARGET:-aarch64-linux-musl}"
OUT="bench/iouring/iouring_smoke"

# Stub turbo_build_options so iouring.zig compiles standalone without the
# whole turbonet build graph.
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
cat > "$STUB_DIR/turbo_build_options.zig" <<EOF
pub const iouring_enabled: bool = true;
EOF

echo "==> cross-compiling iouring smoke for $TARGET"
zig build-exe -target "$TARGET" -O ReleaseSafe -femit-bin="$OUT" \
    --dep iouring \
    -Mroot=bench/iouring/iouring_smoke.zig \
    --dep turbo_build_options \
    -Miouring=zig/src/iouring.zig \
    -Mturbo_build_options="$STUB_DIR/turbo_build_options.zig"

file "$OUT"
echo "==> built $OUT"
