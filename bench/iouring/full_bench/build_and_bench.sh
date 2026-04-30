#!/usr/bin/env bash
# A/B bench the Zig backend with and without -Diouring=true across three
# workloads:
#
#   noargs    GET /                         (trivial baseline)
#   user_id   GET /user/{id}  with {id} varied every request (lua)
#   query     GET /q?id={id}  with {id} varied every request (lua)
#
# Each (variant, workload) pair runs ITERS times; we report the median
# Requests/sec and p50/p99.
#
# Honest scope: in PR #144 the ONLY functional difference between the
# two builds is the accept loop (IORING_OP_ACCEPT_MULTISHOT vs blocking
# accept(2)). Per-connection recv/send still goes through the same
# thread-pool syscalls in both builds. Treat any delta as an accept-path
# delta, not a holistic "io_uring vs syscalls" number.
#
# Env:
#   DURATION   wrk duration (default 10s)
#   THREADS    wrk threads (default 4)
#   CONNS      wrk connections (default 64)
#   PORT       app port (default 8080)
#   WARMUP     warmup seconds per (variant, workload) (default 3)
#   ITERS      measured iterations per (variant, workload) (default 3)

set -euo pipefail

DURATION="${DURATION:-10s}"
THREADS="${THREADS:-4}"
CONNS="${CONNS:-64}"
PORT="${PORT:-8080}"
WARMUP="${WARMUP:-3}"
ITERS="${ITERS:-5}"

REPO="/work"
BENCH_DIR="/work/bench/iouring/full_bench"
RESULTS_DIR="$BENCH_DIR/results"
APP="/app/app.py"
UV="/root/.local/bin/uv"

cd "$REPO"
export PATH="/root/.local/bin:/opt/zig:${PATH}"

PY="$($UV python find 3.14t)"
echo "[bench] using python: $PY"
"$PY" -c "import sys; print('[bench] gil enabled =', sys._is_gil_enabled())"

PY_INC="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
PY_LIB="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"

VENV="/tmp/bench-venv"
"$UV" venv --python "$PY" "$VENV" >/dev/null
PY="$VENV/bin/python"
"$UV" pip install --python "$PY" setuptools wheel >/dev/null
"$UV" pip install --python "$PY" --no-build-isolation -e . >/dev/null

mkdir -p "$RESULTS_DIR"

build_variant() {
    local label="$1"
    local iouring_flag="$2"
    echo "[bench] ==> building variant: $label (iouring=$iouring_flag)"
    ( cd zig && zig build \
        -Dpython=3.14t \
        -Dpy-include="$PY_INC" \
        -Dpy-libdir="$PY_LIB" \
        -Diouring="$iouring_flag" \
        -Doptimize=ReleaseFast )

    local suffix
    suffix="$("$PY" -c 'import importlib.machinery as m; print(m.EXTENSION_SUFFIXES[0])')"
    cp "zig/zig-out/lib/libturbonet.so" "python/turboapi/turbonet${suffix}"
}

start_app() {
    local label="$1"
    "$PY" "$APP" >/tmp/app-"$label".log 2>&1 &
    APP_PID=$!
    local tries=0
    until curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; do
        tries=$((tries + 1))
        if [ "$tries" -gt 100 ]; then
            echo "[bench] app failed to start, log:"; cat /tmp/app-"$label".log || true
            kill "$APP_PID" 2>/dev/null || true
            return 1
        fi
        sleep 0.1
    done
    echo "[bench] app up (pid=$APP_PID, variant=$label)"
}

stop_app() {
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
    sleep 1
}

# run_workload VARIANT WORKLOAD WRK_ARGS...
# writes per-iteration wrk output to $RESULTS_DIR/$VARIANT-$WORKLOAD-$i.txt
run_workload() {
    local variant="$1"; shift
    local workload="$1"; shift

    # warmup
    wrk -t"$THREADS" -c"$CONNS" -d"${WARMUP}s" "$@" >/dev/null

    for i in $(seq 1 "$ITERS"); do
        local out="$RESULTS_DIR/${variant}-${workload}-${i}.txt"
        echo "[bench] ==> wrk variant=$variant workload=$workload iter=$i"
        wrk -t"$THREADS" -c"$CONNS" -d"$DURATION" --latency "$@" >"$out"
    done
}

# --- run both variants, all workloads ---
for variant_spec in "blocking:false" "iouring:true"; do
    variant="${variant_spec%%:*}"
    flag="${variant_spec##*:}"

    build_variant "$variant" "$flag"
    start_app "$variant"

    run_workload "$variant" "noargs"  "http://127.0.0.1:${PORT}/"
    run_workload "$variant" "user_id" -s "$BENCH_DIR/vary_user_id.lua" "http://127.0.0.1:${PORT}"
    run_workload "$variant" "query"   -s "$BENCH_DIR/vary_query.lua"   "http://127.0.0.1:${PORT}"
    run_workload "$variant" "items"   "http://127.0.0.1:${PORT}/items"

    stop_app
done

# --- summarize: pick median req/s across ITERS for each (variant, workload) ---
summarize() {
    local variant="$1"
    local workload="$2"
    # extract req/s from each iter, sort, take median
    local rps
    rps=$(for i in $(seq 1 "$ITERS"); do
            grep -E "^Requests/sec:" "$RESULTS_DIR/${variant}-${workload}-${i}.txt" | awk '{print $2}'
          done | sort -n | awk "NR==$(( (ITERS+1)/2 )) {print}")
    # pick the file matching that rps for p50/p99
    local src
    for i in $(seq 1 "$ITERS"); do
        local f="$RESULTS_DIR/${variant}-${workload}-${i}.txt"
        if grep -qE "^Requests/sec:[[:space:]]+${rps}\$" "$f"; then src="$f"; break; fi
    done
    local p50 p99
    # match the Latency Distribution lines (leading whitespace + percentile),
    # not "55.50%" or "67.00%" stdev values on the Thread Stats line.
    p50=$(awk '/^[[:space:]]+50%[[:space:]]/ {print $2; exit}' "$src")
    p99=$(awk '/^[[:space:]]+99%[[:space:]]/ {print $2; exit}' "$src")
    printf "  %-8s  %-8s  req/s=%-12s  p50=%-8s  p99=%-8s\n" \
        "$variant" "$workload" "$rps" "$p50" "$p99"
}

echo
echo "===================== MEDIAN OF $ITERS RUNS ====================="
for workload in noargs user_id query items; do
    summarize blocking "$workload"
    summarize iouring  "$workload"
done
echo "================================================================="
echo "Raw iter outputs: $RESULTS_DIR/"
echo "Kernel: $(uname -r)  |  wrk: t=$THREADS c=$CONNS d=$DURATION  |  iters=$ITERS"
echo "NOTE: only the accept loop differs between variants. Treat deltas accordingly."
