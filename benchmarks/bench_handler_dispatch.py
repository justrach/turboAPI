"""
Microbench for `create_fast_handler` per-request closure dispatch.

Measures the Python-side cost of running a single fast-handler call, isolated
from the Zig HTTP server. Used to prove Python-side hot-path changes have
measurable impact at the level they actually change (per-request closure body),
since the end-to-end `bench_regression.py` HTTP throughput has ~15-20%
run-to-run noise that hides 1-2% Python-side wins.

Run:
    .venv314t/bin/python benchmarks/bench_handler_dispatch.py

Reports median + p99 over N=200_000 dispatches, four call shapes:
  * noargs   — 0-param handler
  * pathonly — 1 path param, no query, no body
  * pathqs   — 1 path param + query string (exercises parse_qs path)
  * patherr  — handler raises HTTPException (exercises exception path)
"""

from __future__ import annotations

import statistics
import time
from typing import Callable

from turboapi.exceptions import HTTPException
from turboapi.request_handler import create_fast_handler
from turboapi.routing import HTTPMethod, RouteDefinition


# --- handlers -----------------------------------------------------------

def h_noargs():
    return {"ok": True}


def h_pathonly(user_id: int):
    return {"id": user_id}


def h_pathqs(user_id: int, q: str = ""):
    return {"id": user_id, "q": q}


def h_raises(user_id: int):
    raise HTTPException(status_code=404, detail="not found")


# --- helpers ------------------------------------------------------------

def make_route(method: HTTPMethod = HTTPMethod.GET, path: str = "/x") -> RouteDefinition:
    return RouteDefinition(
        path=path,
        method=method,
        handler=lambda: None,
        path_params=[],
        query_params={},
    )


def time_dispatch(fast: Callable, kwargs: dict, n: int) -> tuple[float, float]:
    # Warmup
    for _ in range(min(2_000, n // 10)):
        fast(**kwargs)
    t0 = time.perf_counter_ns()
    for _ in range(n):
        fast(**kwargs)
    t1 = time.perf_counter_ns()
    median_ns = (t1 - t0) // n
    # Per-call samples for p99 from a smaller pass.
    samples_ns: list[int] = []
    for _ in range(min(20_000, n // 10)):
        ts = time.perf_counter_ns()
        fast(**kwargs)
        samples_ns.append(time.perf_counter_ns() - ts)
    p99_ns = sorted(samples_ns)[int(len(samples_ns) * 0.99)]
    return median_ns, p99_ns


# --- benches ------------------------------------------------------------

def bench_noargs(n: int) -> tuple[float, float]:
    fast = create_fast_handler(h_noargs, make_route())
    return time_dispatch(fast, {}, n)


def bench_pathonly(n: int) -> tuple[float, float]:
    fast = create_fast_handler(h_pathonly, make_route(path="/users/{user_id}"))
    return time_dispatch(fast, {"path_params": {"user_id": "42"}}, n)


def bench_pathqs(n: int) -> tuple[float, float]:
    fast = create_fast_handler(h_pathqs, make_route(path="/users/{user_id}"))
    return time_dispatch(
        fast,
        {"path_params": {"user_id": "42"}, "query_string": "q=hello&extra=1"},
        n,
    )


def bench_patherr(n: int) -> tuple[float, float]:
    fast = create_fast_handler(h_raises, make_route(path="/users/{user_id}"))
    return time_dispatch(fast, {"path_params": {"user_id": "42"}}, n)


# --- driver -------------------------------------------------------------

def main() -> None:
    runs = 5
    n = 200_000

    cases = [
        ("noargs", bench_noargs),
        ("pathonly", bench_pathonly),
        ("pathqs", bench_pathqs),
        ("patherr", bench_patherr),
    ]

    print(f"create_fast_handler dispatch microbench  (n={n} per case, {runs} runs)")
    print(f"{'case':<10} {'median_us':>11} {'p99_us':>10}")
    for name, fn in cases:
        med_runs = []
        p99_runs = []
        for _ in range(runs):
            m, p = fn(n)
            med_runs.append(m)
            p99_runs.append(p)
        med_us = statistics.median(med_runs) / 1000
        p99_us = statistics.median(p99_runs) / 1000
        print(f"{name:<10} {med_us:>11.3f} {p99_us:>10.3f}")


if __name__ == "__main__":
    main()
