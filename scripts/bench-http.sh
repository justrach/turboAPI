#!/usr/bin/env bash
# Run the local HTTP regression benchmark with the worker count recorded.
#
# Example:
#   WORKERS=4 ./scripts/bench-http.sh --history

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

WORKER_COUNT="${WORKERS:-${BENCH_WORKERS:-${TURBO_THREAD_POOL_SIZE:-24}}}"
export WORKERS="$WORKER_COUNT"
export BENCH_WORKERS="$WORKER_COUNT"
export TURBO_THREAD_POOL_SIZE="$WORKER_COUNT"

echo "HTTP benchmark config:"
echo "  workers:     $WORKER_COUNT"
echo "  wrk threads: ${BENCH_THREADS:-4}"
echo "  connections: ${BENCH_CONNECTIONS:-100}"
echo "  duration:    ${BENCH_DURATION:-10}s"
echo ""

exec "$PYTHON_BIN" "$ROOT/benchmarks/bench_regression.py" "$@"
