#!/usr/bin/env python3
"""
Local-side benchmark for TurboPG execute_many modes.

Runs the same insert workload with:
  - dynamic protocol batching
  - multi-VALUES SQL batching

Each case is executed in a fresh subprocess so the native pool state stays clean.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

CONN = os.environ.get("BENCH_CONN", "postgres://postgres@127.0.0.1:5432/postgres")
POOL = int(os.environ.get("BENCH_POOL", "32"))
WORKERS = int(os.environ.get("BENCH_WORKERS", "32"))
WARMUP = float(os.environ.get("BENCH_WARMUP", "1.0"))
DURATION = float(os.environ.get("BENCH_DURATION", "5.0"))

SQL = (
    "INSERT INTO _exec_many_compare_local "
    "(a, b, c, d, e, f, g) VALUES ($1, $2, $3, $4, $5, $6, $7)"
)


def repeated_rows(count: int) -> list[list]:
    row = [10, True, 10, "TESTTESTTEST", 10.333, 12341234, 123412341234]
    return [row[:] for _ in range(count)]


def varied_rows(count: int) -> list[list]:
    rows = []
    for i in range(count):
        rows.append([i, bool(i % 2), i + 2, f"row_{i}", 10.333 + i, 12340000 + i, 123412340000 + i])
    return rows


def mixed_rows(count: int) -> list[list]:
    rows = []
    for i in range(count):
        rows.append([
            i if i % 5 else None,
            bool(i % 2),
            -(i + 2),
            f"mixed_{i}" if i % 7 else "",
            10.333 + (i / 10),
            None if i % 9 == 0 else 12340000 + i,
            123412340000 + i,
        ])
    return rows


def rows_for_case(case: str) -> list[list]:
    if case == "repeated_1000":
        return repeated_rows(1000)
    if case == "varied_1000":
        return varied_rows(1000)
    if case == "mixed_1000":
        return mixed_rows(1000)
    if case == "repeated_100":
        return repeated_rows(100)
    if case == "varied_100":
        return varied_rows(100)
    if case == "mixed_100":
        return mixed_rows(100)
    raise SystemExit(f"unknown case: {case}")


def setup_table(db) -> None:
    db.execute("DROP TABLE IF EXISTS _exec_many_compare_local")
    db.execute(
        "CREATE TABLE _exec_many_compare_local ("
        "a bigint, b boolean, c bigint, d text, e double precision, f bigint, g bigint)"
    )


def run_case(mode: str, case: str) -> dict:
    os.environ["TURBOPG_EXEC_MANY_MODE"] = mode
    from turbopg.client import Database

    db = Database(CONN, pool_size=POOL)
    rows = rows_for_case(case)
    setup_table(db)

    stop = False

    def worker() -> int:
        nonlocal stop
        local = 0
        while not stop:
            db.execute_many(SQL, rows)
            local += 1
        return local

    warm_end = time.perf_counter() + WARMUP
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(worker) for _ in range(WORKERS)]
        while time.perf_counter() < warm_end:
            time.sleep(0.05)
        stop = True
        _ = sum(f.result() for f in futs)

    setup_table(db)
    stop = False
    start = time.perf_counter()
    end_at = start + DURATION
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(worker) for _ in range(WORKERS)]
        while time.perf_counter() < end_at:
            time.sleep(0.05)
        stop = True
        measured = sum(f.result() for f in futs)
    elapsed = time.perf_counter() - start

    count_row = db.query_one("SELECT count(*) AS count FROM _exec_many_compare_local")
    db.execute("DROP TABLE _exec_many_compare_local")
    return {
        "mode": mode,
        "case": case,
        "batch_rows": len(rows),
        "batches": measured,
        "elapsed_s": round(elapsed, 3),
        "qps": round(measured / elapsed, 1),
        "rows_per_s": round((measured * len(rows)) / elapsed, 1),
        "table_rows": count_row["count"],
    }


def run_child(mode: str, case: str) -> dict:
    env = os.environ.copy()
    env["PYTHON_GIL"] = env.get("PYTHON_GIL", "0")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"python:{existing}" if existing else "python"
    proc = subprocess.run(
        [sys.executable, __file__, "--mode", mode, "--case", case],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return ast.literal_eval(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dynamic", "multi_values"])
    parser.add_argument(
        "--case",
        choices=[
            "repeated_1000",
            "varied_1000",
            "mixed_1000",
            "repeated_100",
            "varied_100",
            "mixed_100",
        ],
    )
    args = parser.parse_args()

    if args.mode and args.case:
        print(run_case(args.mode, args.case))
        return

    cases = [
        "repeated_1000",
        "varied_1000",
        "mixed_1000",
        "repeated_100",
        "varied_100",
        "mixed_100",
    ]

    results = []
    for case in cases:
        results.append(run_child("dynamic", case))
        results.append(run_child("multi_values", case))

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
