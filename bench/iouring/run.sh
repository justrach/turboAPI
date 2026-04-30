#!/usr/bin/env bash
# End-to-end: build the io_uring smoke binary, package it into an OCI image,
# run it inside Apple `container` (or any compatible runtime), and check the
# exit code.
#
# This validates that:
#   * zig/src/iouring.zig compiles for Linux
#   * std.os.linux.IoUring works on the kernel inside Apple's lightweight VM
#   * IORING_OP_ACCEPT_MULTISHOT delivers all expected accepts
#
# This is a correctness check, NOT a benchmark. Per AGENTS.md, no perf
# numbers should be cited from this script.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BENCH_DIR="$REPO_ROOT/bench/iouring"
RUNTIME="${RUNTIME:-container}"
IMAGE="${IMAGE:-turboapi-iouring-smoke:latest}"
NAME="${NAME:-turboapi-iouring-smoke}"

cd "$REPO_ROOT"

# 1. Build the static Linux binary on the host.
"$BENCH_DIR/build.sh"

# 2. Build the OCI image.
echo "==> building $IMAGE via $RUNTIME"
"$RUNTIME" build -t "$IMAGE" -f "$BENCH_DIR/Containerfile" "$BENCH_DIR"

# 3. Run it; non-zero exit => smoke test failed.
echo "==> running smoke test"
"$RUNTIME" rm -f "$NAME" 2>/dev/null || true
if "$RUNTIME" run --rm --name "$NAME" "$IMAGE"; then
    echo "==> io_uring smoke test PASSED"
else
    rc=$?
    echo "==> io_uring smoke test FAILED (exit $rc)" >&2
    exit "$rc"
fi
