"""
Microbench for #158 — drop wasted `{}` defaults in `kwargs.get("headers", ...)`
across `create_enhanced_handler` (the slow / Depends path).

Six sites patched in two functions (sync + async enhanced_handler):

  * 4 sites: `kwargs.get("headers", {})` → `kwargs.get("headers")`
            (followed by `if d:` / used only when truthy).
  * 2 sites: `kwargs.get("headers", {}) or {}` → `kwargs.get("headers") or {}`
            (the `or {}` already coerces; the inner default was
             allocating `{}` on every present-headers call).

Per-call savings is one wasted `PyDict_New` per site. The enhanced_handler
runs every dependency-injection / Form / File / raw-body request, so this
is straight-line wins on the slow path.

This bench isolates the four shapes used in the patch:

  * default_no_hdr     :: kwargs.get("k", {})        with key absent — old behavior
  * no_default_no_hdr  :: kwargs.get("k")            with key absent — new
  * default_or_w_hdr   :: kwargs.get("k", {}) or {}  with key present — old
  * no_default_or_w_hdr:: kwargs.get("k") or {}      with key present — new

Run:
    .venv/bin/python benchmarks/bench_enhanced_handler_headers_default.py
"""

from __future__ import annotations

import statistics
import time


def time_op(op, n: int) -> tuple[float, float]:
    for _ in range(min(20_000, n // 10)):
        op()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        op()
    t1 = time.perf_counter_ns()
    median_ns = (t1 - t0) / n
    samples_ns: list[int] = []
    for _ in range(min(20_000, n // 10)):
        ts = time.perf_counter_ns()
        op()
        samples_ns.append(time.perf_counter_ns() - ts)
    p99_ns = sorted(samples_ns)[int(len(samples_ns) * 0.99)]
    return median_ns, p99_ns


def bench_default_no_hdr(n: int) -> tuple[float, float]:
    kw = {"path": "/x", "query_string": ""}  # no headers
    def op():
        h = kw.get("headers", {})
        if h:
            pass
    return time_op(op, n)


def bench_no_default_no_hdr(n: int) -> tuple[float, float]:
    kw = {"path": "/x", "query_string": ""}
    def op():
        h = kw.get("headers")
        if h:
            pass
    return time_op(op, n)


def bench_default_or_w_hdr(n: int) -> tuple[float, float]:
    # Common path: headers IS present (Zig backend always passes headers).
    # Old code allocates `{}` for the .get() default arg AND throws it away.
    kw = {"path": "/x", "headers": {"x-token": "abc"}}
    def op():
        h = kw.get("headers", {}) or {}
        return h
    return time_op(op, n)


def bench_no_default_or_w_hdr(n: int) -> tuple[float, float]:
    kw = {"path": "/x", "headers": {"x-token": "abc"}}
    def op():
        h = kw.get("headers") or {}
        return h
    return time_op(op, n)


def main() -> None:
    runs = 5
    n = 1_000_000

    cases = [
        ("default_no_hdr",      bench_default_no_hdr),
        ("no_default_no_hdr",   bench_no_default_no_hdr),
        ("default_or_w_hdr",    bench_default_or_w_hdr),
        ("no_default_or_w_hdr", bench_no_default_or_w_hdr),
    ]

    print(f"enhanced_handler kwargs.get('headers', ...) microbench  (n={n} per case, {runs} runs)")
    print(f"{'case':<22} {'median_ns':>11} {'p99_ns':>10}")
    for name, fn in cases:
        med_runs = []
        p99_runs = []
        for _ in range(runs):
            m, p = fn(n)
            med_runs.append(m)
            p99_runs.append(p)
        print(f"{name:<22} {statistics.median(med_runs):>11.1f} {statistics.median(p99_runs):>10.1f}")


if __name__ == "__main__":
    main()
