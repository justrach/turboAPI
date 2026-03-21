#!/bin/bash
set -euo pipefail

# ── Wait for LocalStack to be ready ──────────────────────────────────────────
LOCALSTACK_URL="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
MAX_WAIT=60
WAITED=0

echo "==> Waiting for LocalStack at ${LOCALSTACK_URL} ..."
until curl -sf "${LOCALSTACK_URL}/_localstack/health" > /dev/null 2>&1; do
    WAITED=$((WAITED + 1))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "ERROR: LocalStack not ready after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 1
done
echo "==> LocalStack is ready (waited ${WAITED}s)"

# ── Run parity tests ────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Running parity tests"
echo "================================================================"
PYTHONPATH=/app pytest tests/test_s3_parity.py -v --tb=short -x
TEST_EXIT=$?

# ── Run benchmarks ──────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Running benchmarks"
echo "================================================================"
PYTHONPATH=/app python benchmarks/s3_bench.py --quick --json 2>&1

echo ""
echo "==> All done."
exit ${TEST_EXIT}
