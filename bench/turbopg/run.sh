#!/usr/bin/env bash
# Runs the turbopg A/B bench against a PG18 instance reachable at
# $PGHOST:$PGPORT. Builds both variants in-place inside this container
# (using the bind-mounted repo at /work).
#
# Env:
#   PGHOST, PGPORT, PGUSER, PGDATABASE
#   BENCH_THREADS, BENCH_DURATION, BENCH_QUERY, BENCH_ITERS
set -euo pipefail

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-postgres}"
BENCH_THREADS="${BENCH_THREADS:-4}"
BENCH_DURATION="${BENCH_DURATION:-10}"
BENCH_QUERY="${BENCH_QUERY:-1}"
BENCH_ITERS="${BENCH_ITERS:-3}"

export PGHOST PGPORT PGUSER PGDATABASE BENCH_THREADS BENCH_DURATION BENCH_QUERY

echo "[bench] waiting for postgres at $PGHOST:$PGPORT ..."
for i in $(seq 1 60); do
    if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -q; then
        echo "[bench] postgres up after ${i}s"
        break
    fi
    sleep 1
done
if ! pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -q; then
    echo "[bench] postgres never came up" >&2
    exit 1
fi

cd /work/bench/turbopg

build_variant() {
    local label="$1"
    local flag="$2"
    echo "[bench] ==> building variant: $label (iouring=$flag)"
    rm -rf zig-out .zig-cache
    zig build -Doptimize=ReleaseFast -Diouring="$flag"
}

run_variant() {
    local label="$1"
    echo "[bench] ==> running $BENCH_ITERS iters: variant=$label threads=$BENCH_THREADS duration=${BENCH_DURATION}s query=$BENCH_QUERY"
    mkdir -p /work/bench/turbopg/results
    for i in $(seq 1 "$BENCH_ITERS"); do
        BENCH_LABEL="$label" \
            ./zig-out/bin/turbopg-bench \
            2> "/work/bench/turbopg/results/${label}-q${BENCH_QUERY}-${i}.txt" \
            || { cat "/work/bench/turbopg/results/${label}-q${BENCH_QUERY}-${i}.txt"; exit 1; }
        grep "^\[bench\] result" "/work/bench/turbopg/results/${label}-q${BENCH_QUERY}-${i}.txt"
    done
}

summarize() {
    local label="$1"
    local q="$2"
    # Pull rps from each iteration, sort, take median
    python3 - <<EOF
import glob, re, statistics
pat = re.compile(r"rps=([0-9.]+)")
rows = sorted(
    float(pat.search(open(f).read()).group(1))
    for f in glob.glob("/work/bench/turbopg/results/${label}-q${q}-*.txt")
    if pat.search(open(f).read())
)
if rows:
    med = statistics.median(rows)
    mn = min(rows)
    mx = max(rows)
    print(f"  {'${label}':<10}  q={'${q}'}  med={med:10.2f} rps  min={mn:10.2f}  max={mx:10.2f}  n={len(rows)}")
else:
    print(f"  {'${label}':<10}  q={'${q}'}  NO DATA")
EOF
}

build_variant blocking false
run_variant   blocking

build_variant iouring  true
run_variant   iouring

echo
echo "===================== MEDIAN OF $BENCH_ITERS RUNS (query=$BENCH_QUERY) ====================="
summarize blocking "$BENCH_QUERY"
summarize iouring  "$BENCH_QUERY"
echo "========================================================================"
echo "kernel: $(uname -r)  threads=$BENCH_THREADS duration=${BENCH_DURATION}s"
echo "NOTE: single-conn-per-thread, no pool. Only transport differs between variants."
