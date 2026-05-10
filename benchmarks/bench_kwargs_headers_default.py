"""
Microbench for PR #151 — drop the `{}` default in `kwargs.get("headers", {})`.

The two patched sites are inside `create_fast_handler` and
`create_fast_async_handler`, in the branch that runs when a handler has
parameters left unfilled by path/query parsing. On every such request, the
old code allocated an empty dict via `PyDict_New` and discarded it
whenever no headers were present. The new code returns `None` and is
short-circuited by the existing `if headers:` immediately following.

The change is a single bytecode-level swap (LOAD_CONST {} → LOAD_CONST
None) that removes one `PyDict_New` per fast-handler call that:
  (a) has unfilled params (e.g. a Header(...) param), AND
  (b) arrived without `headers` in kwargs.

Because the per-call savings is only the alloc itself (~50 ns), this
bench isolates that exact line in a tight loop rather than full-dispatch
end-to-end — full dispatch is ~2 us and the noise floor would swallow a
single dict alloc. The two cases mirror the two equivalent forms used in
the codebase before/after the patch.

Run:
    .venv/bin/python benchmarks/bench_kwargs_headers_default.py
"""

from __future__ import annotations

import statistics
import time


def time_op(op, n: int) -> tuple[float, float]:
    # Warmup
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


def make_with_default_kwargs() -> dict:
    # Realistic shape: path_params present, no headers key. This is the
    # common case that triggered the wasted PyDict_New on every request.
    return {"path_params": {"user_id": "42"}, "query_string": "q=hello"}


def bench_with_empty_dict_default(n: int) -> tuple[float, float]:
    kw = make_with_default_kwargs()
    def op() -> None:
        h = kw.get("headers", {})
        if h:
            pass
    return time_op(op, n)


def bench_no_default(n: int) -> tuple[float, float]:
    kw = make_with_default_kwargs()
    def op() -> None:
        h = kw.get("headers")
        if h:
            pass
    return time_op(op, n)


def bench_with_headers_present_old(n: int) -> tuple[float, float]:
    # Control: when `headers` IS present, the default is never returned, so
    # both forms should be indistinguishable. Verifies the change has no
    # cost on the fast-path.
    kw = {"path_params": {"user_id": "42"}, "headers": {"x-token": "abc"}}
    def op() -> None:
        h = kw.get("headers", {})
        if h:
            pass
    return time_op(op, n)


def bench_with_headers_present_new(n: int) -> tuple[float, float]:
    kw = {"path_params": {"user_id": "42"}, "headers": {"x-token": "abc"}}
    def op() -> None:
        h = kw.get("headers")
        if h:
            pass
    return time_op(op, n)


def main() -> None:
    runs = 5
    n = 1_000_000

    cases = [
        ("default_{}_no_hdr", bench_with_empty_dict_default),  # old (had alloc)
        ("no_default_no_hdr", bench_no_default),               # new (no alloc)
        ("default_{}_w_hdr", bench_with_headers_present_old),  # control: default unused
        ("no_default_w_hdr", bench_with_headers_present_new),  # control: identical
    ]

    print(f"kwargs.get('headers', ...) microbench  (n={n} per case, {runs} runs)")
    print(f"{'case':<22} {'median_ns':>11} {'p99_ns':>10}")
    for name, fn in cases:
        med_runs = []
        p99_runs = []
        for _ in range(runs):
            m, p = fn(n)
            med_runs.append(m)
            p99_runs.append(p)
        med_ns = statistics.median(med_runs)
        p99_ns = statistics.median(p99_runs)
        print(f"{name:<22} {med_ns:>11.1f} {p99_ns:>10.1f}")


if __name__ == "__main__":
    main()
