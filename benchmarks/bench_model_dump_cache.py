"""
Microbench for PR #150 — cache `model_dump` detection at handler-creation time.

`create_fast_handler` and `create_fast_async_handler` previously ran
`hasattr(result, "model_dump")` on every response. The new code calls
`_returns_model(original_handler)` once at creation time and consults the
cached True/False/None at dispatch — type-stable handlers (those with
a return annotation pointing at either a Pydantic/dhi model or a known
leaf type like `dict`) skip the per-response hasattr entirely.

This bench exercises `create_fast_handler.fast_handler_noargs` (the
hottest dispatch path — zero-arg handler, single tuple return) with three
return-annotation shapes:
  * leaf      — `-> dict` : new code skips hasattr (-O(1) win)
  * model     — `-> Item` : new code skips hasattr AND knows to call
                            model_dump directly (no test needed)
  * unannot   — no annot : new code falls back to hasattr (control —
                           should match the pre-PR baseline within noise)

Run:
    .venv/bin/python benchmarks/bench_model_dump_cache.py
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

from dhi import BaseModel
from turboapi.request_handler import create_fast_handler
from turboapi.routing import HTTPMethod, RouteDefinition


class Item(BaseModel):
    name: str
    qty: int


def h_leaf() -> dict:
    return {"ok": True}


def h_model() -> Item:
    return Item(name="widget", qty=1)


def h_unannot():
    return {"ok": True}


def make_route() -> RouteDefinition:
    return RouteDefinition(
        path="/x",
        method=HTTPMethod.GET,
        handler=lambda: None,
        path_params=[],
        query_params={},
    )


def time_dispatch(fast: Callable, n: int) -> tuple[float, float]:
    for _ in range(min(2_000, n // 10)):
        fast()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        fast()
    t1 = time.perf_counter_ns()
    median_ns = (t1 - t0) / n
    samples_ns: list[int] = []
    for _ in range(min(20_000, n // 10)):
        ts = time.perf_counter_ns()
        fast()
        samples_ns.append(time.perf_counter_ns() - ts)
    p99_ns = sorted(samples_ns)[int(len(samples_ns) * 0.99)]
    return median_ns, p99_ns


def bench_leaf(n: int) -> tuple[float, float]:
    return time_dispatch(create_fast_handler(h_leaf, make_route()), n)


def bench_model(n: int) -> tuple[float, float]:
    return time_dispatch(create_fast_handler(h_model, make_route()), n)


def bench_unannot(n: int) -> tuple[float, float]:
    return time_dispatch(create_fast_handler(h_unannot, make_route()), n)


def main() -> None:
    runs = 5
    n = 200_000

    cases = [
        ("leaf_dict", bench_leaf),       # -> dict :: skips hasattr (win)
        ("model_dhi", bench_model),       # -> Item :: skips hasattr, direct call (win)
        ("unannot",   bench_unannot),     # no annot :: keeps hasattr (control)
    ]

    print(f"create_fast_handler dispatch microbench  (n={n} per case, {runs} runs)")
    print(f"{'case':<14} {'median_ns':>11} {'p99_ns':>10}")
    for name, fn in cases:
        med_runs = []
        p99_runs = []
        for _ in range(runs):
            m, p = fn(n)
            med_runs.append(m)
            p99_runs.append(p)
        med_ns = statistics.median(med_runs)
        p99_ns = statistics.median(p99_runs)
        print(f"{name:<14} {med_ns:>11.1f} {p99_ns:>10.1f}")


if __name__ == "__main__":
    main()
