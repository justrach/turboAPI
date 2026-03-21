#!/bin/bash
set -e

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PY14="/opt/python3.14t/bin/python3"
VENV_PY="/pgbench/_python/venv/bin/python3"

echo "======================================================================"
echo "MagicStack pgbench + TurboAPI pg.zig -- Postgres 18"
echo "======================================================================"
echo "Postgres: ${PGHOST}:${PGPORT}"
echo "asyncpg/psycopg3: Python 3.11 + uvloop"
echo "TurboAPI+pg.zig:  Python 3.14t free-threaded + Zig"
echo ""

# Parse results using venv python (has numpy)
parse_result() {
    $VENV_PY -c "
import sys, json, numpy as np
with open(sys.argv[1]) as f:
    data = json.load(f)
ls = np.array(data['latency_stats'])
arange = np.arange(len(ls))
mean = np.average(arange, weights=ls) / 100
queries = data['queries']
duration = data['duration']
qps = queries / duration
rows = data['rows']
rps = rows / duration
min_lat = data['min_latency'] / 100
max_lat = data['max_latency'] / 100
print(f'  {queries:,} queries in {duration:.1f}s')
print(f'  Queries/sec: {qps:,.0f}')
print(f'  Rows/sec:    {rps:,.0f}')
print(f'  Latency:     min={min_lat:.3f}ms  mean={mean:.3f}ms  max={max_lat:.3f}ms')
" "$1"
}

run_driver() {
    local LABEL="$1"
    local DRIVER="$2"
    local QUERY="$3"
    local PYTHON="$4"
    local RUNNER="$5"

    echo "--- ${LABEL} (concurrency=10, duration=30s) ---"

    TMPOUT=$(mktemp)
    ${PYTHON} ${RUNNER} \
        --pghost="$PGHOST" \
        --pgport="$PGPORT" \
        --pguser="$PGUSER" \
        --concurrency=10 \
        --duration=30 \
        --warmup-time=5 \
        --output-format=json \
        "$DRIVER" "$QUERY" >"$TMPOUT" 2>/dev/null || true

    if head -c1 "$TMPOUT" | grep -q '{'; then
        parse_result "$TMPOUT"
    else
        echo "  FAILED"
    fi
    rm -f "$TMPOUT"
}

cd /pgbench/_python
source venv/bin/activate

for QUERY in /pgbench/queries/7-oneplusone.json /pgbench/queries/1-pg_type.json /pgbench/queries/2-generate_series.json; do
    QNAME=$(basename "$QUERY" .json)
    echo ""
    echo "=== Query: $QNAME ==="
    echo ""

    # asyncpg (Python 3.11 venv)
    run_driver "asyncpg" "asyncpg" "$QUERY" "$VENV_PY" "pgbench_python.py"

    # psycopg3-async (Python 3.11 venv)
    run_driver "psycopg3-async" "psycopg3-async" "$QUERY" "$VENV_PY" "pgbench_python.py"

    # TurboAPI+pg.zig (Python 3.14t, separate process)
    run_driver "turbopg (pg.zig)" "turbopg" "$QUERY" "$PY14" "/pgbench/pgbench_zig"
done

echo ""
echo "======================================================================"
echo "Done."
echo "======================================================================"
