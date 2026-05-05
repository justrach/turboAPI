"""
Microbench for CORSMiddleware.after_request.

Measures the per-response cost of the CORS header attach step in isolation —
no network, no Zig server, no full request lifecycle. Used to prove the
"cache joined strings + max_age str" optimization has measurable impact on
the targeted code path, since the end-to-end `bench_regression.py` doesn't
include CORS in its test app and so wouldn't show this signal at all.

Run:
    .venv314t/bin/python benchmarks/bench_cors_after_request.py

Reports median + p99 over N=200_000 calls per case.
Cases isolate the with/without expose_headers branch.
"""

from __future__ import annotations

import statistics
import time

from turboapi.middleware.core import CORSMiddleware


# Minimal Request/Response stand-ins. CORSMiddleware.after_request only reads
# request.headers and calls response.set_header — that's the entire surface.

class FakeRequest:
    __slots__ = ("headers", "method")

    def __init__(self) -> None:
        self.headers = {"origin": "http://localhost:8080"}
        self.method = "GET"


class FakeResponse:
    __slots__ = ("_headers",)

    def __init__(self) -> None:
        self._headers: dict[str, str] = {}

    def set_header(self, name: str, value: str) -> None:
        self._headers[name] = value


def time_after_request(mw: CORSMiddleware, n: int) -> tuple[float, float]:
    req = FakeRequest()
    resp = FakeResponse()
    # Warmup
    for _ in range(min(2_000, n // 10)):
        mw.after_request(req, resp)
    # Median over batched wall-clock.
    t0 = time.perf_counter_ns()
    for _ in range(n):
        mw.after_request(req, resp)
    t1 = time.perf_counter_ns()
    median_ns = (t1 - t0) // n
    # Per-call samples for p99.
    samples_ns: list[int] = []
    for _ in range(min(20_000, n // 10)):
        ts = time.perf_counter_ns()
        mw.after_request(req, resp)
        samples_ns.append(time.perf_counter_ns() - ts)
    p99_ns = sorted(samples_ns)[int(len(samples_ns) * 0.99)]
    return median_ns, p99_ns


def bench_default(n: int) -> tuple[float, float]:
    # Default CORS: 7 allow_methods, ["*"] allow_headers, no expose_headers
    mw = CORSMiddleware(allow_origins=["http://localhost:8080"])
    return time_after_request(mw, n)


def bench_with_expose(n: int) -> tuple[float, float]:
    mw = CORSMiddleware(
        allow_origins=["http://localhost:8080"],
        expose_headers=["X-Trace-Id", "X-Custom-Header", "X-Build-Id"],
    )
    return time_after_request(mw, n)


def bench_credentials(n: int) -> tuple[float, float]:
    mw = CORSMiddleware(
        allow_origins=["http://localhost:8080"],
        allow_credentials=True,
    )
    return time_after_request(mw, n)


def main() -> None:
    runs = 5
    n = 200_000

    cases = [
        ("default",     bench_default),
        ("with_expose", bench_with_expose),
        ("credentials", bench_credentials),
    ]

    print(f"CORSMiddleware.after_request microbench  (n={n} per case, {runs} runs)")
    print(f"{'case':<14} {'median_us':>11} {'p99_us':>10}")
    for name, fn in cases:
        med_runs = []
        p99_runs = []
        for _ in range(runs):
            m, p = fn(n)
            med_runs.append(m)
            p99_runs.append(p)
        med_us = statistics.median(med_runs) / 1000
        p99_us = statistics.median(p99_runs) / 1000
        print(f"{name:<14} {med_us:>11.3f} {p99_us:>10.3f}")


if __name__ == "__main__":
    main()
