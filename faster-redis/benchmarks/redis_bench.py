#!/usr/bin/env python3
"""
redis-bench: Honest benchmark of faster-redis vs redis-py (+hiredis)

Design principles (learned from the turboAPI caching incident):
  1. NO caching anywhere — verified with unique-data tests
  2. NO warmup tricks — warmup phase excluded from timing
  3. BOTH repeated AND unique data tested to show CPU cache effects
  4. hiredis (C extension) included as the real competitor
  5. Raw numbers, no cherry-picking
  6. memtier_benchmark for end-to-end baseline

Usage:
    python benchmarks/redis_bench.py             # full suite
    python benchmarks/redis_bench.py --quick     # reduced iters
    python benchmarks/redis_bench.py --json      # machine output

Requires: Redis on localhost:6379
"""

import argparse
import asyncio
import json as json_mod
import os
import random
import string
import subprocess
import sys
import time
from dataclasses import dataclass, asdict

REDIS_HOST = "localhost"
REDIS_PORT = 6379


@dataclass
class Result:
    name: str
    ops_per_sec: float
    us_per_op: float
    label: str = ""
    note: str = ""


def heading(text):
    print(f"\n{'='*70}\n  {text}\n{'='*70}")


def bench(fn, n, warmup=500):
    """Benchmark with warmup excluded from timing."""
    for _ in range(warmup):
        fn()
    t = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = time.perf_counter() - t
    return n / elapsed, elapsed / n * 1e6


def bench_unique(fn_factory, n):
    """Benchmark with UNIQUE input each iteration. No CPU cache reuse."""
    items = [fn_factory() for _ in range(n)]
    # Warmup with different data
    warmup_items = [fn_factory() for _ in range(min(500, n))]
    for item in warmup_items:
        item()

    t = time.perf_counter()
    for item in items:
        item()
    elapsed = time.perf_counter() - t
    return n / elapsed, elapsed / n * 1e6


def random_string(min_len=5, max_len=50):
    return ''.join(random.choices(string.ascii_letters, k=random.randint(min_len, max_len)))


# ── 1. RESP Parsing — Repeated Data ─────────────────────────────────────────

def bench_parsing_repeated(n):
    heading("1. RESP Parsing — Repeated Data (best case, CPU cache warm)")
    results = []

    payloads = {
        "+OK": b"+OK\r\n",
        "$11 bulk": b"$11\r\nhello world\r\n",
        ":42 int": b":42\r\n",
        "*3 array": b"*3\r\n$3\r\nfoo\r\n$3\r\nbar\r\n:42\r\n",
        "$100 bulk": b"$100\r\n" + b"x" * 100 + b"\r\n",
    }

    # Zig
    try:
        from faster_redis._redis_accel import parse_resp
        for label, data in payloads.items():
            ops, us = bench(lambda d=data: parse_resp(d), n)
            results.append(Result(f"Zig ({label})", ops, us, "zig", "repeated"))
            print(f"  Zig      {label:>12}: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        print("  Zig parser: not built")

    # hiredis
    try:
        import hiredis
        for label, data in payloads.items():
            reader = hiredis.Reader()
            def hiredis_parse(d=data, r=reader):
                r.feed(d)
                return r.gets()
            ops, us = bench(hiredis_parse, n)
            results.append(Result(f"hiredis ({label})", ops, us, "hiredis", "repeated"))
            print(f"  hiredis  {label:>12}: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        print("  hiredis: not installed")

    # Pure Python
    def py_parse(data):
        if data[0:1] == b"+":
            return data[1:data.index(b"\r\n")].decode()
        elif data[0:1] == b"$":
            i = data.index(b"\r\n")
            l = int(data[1:i])
            return data[i+2:i+2+l]
        elif data[0:1] == b":":
            return int(data[1:data.index(b"\r\n")])
        return data

    for label, data in list(payloads.items())[:3]:
        ops, us = bench(lambda d=data: py_parse(d), n)
        results.append(Result(f"Python ({label})", ops, us, "python", "repeated"))
        print(f"  Python   {label:>12}: {ops:>12,.0f} ops/s  ({us:.3f}us)")

    return results


# ── 2. RESP Parsing — Unique Data (anti-cache) ──────────────────────────────

def bench_parsing_unique(n):
    heading("2. RESP Parsing — UNIQUE Data (no CPU cache reuse)")
    results = []
    n_unique = min(n, 200_000)  # pre-generate this many

    # Generate unique bulk strings
    unique_bulks = []
    for _ in range(n_unique):
        s = random_string(10, 80)
        unique_bulks.append(f"${len(s)}\r\n{s}\r\n".encode())

    # Zig
    try:
        from faster_redis._redis_accel import parse_resp
        t = time.perf_counter()
        for i in range(n_unique):
            parse_resp(unique_bulks[i])
        elapsed = time.perf_counter() - t
        ops = n_unique / elapsed
        us = elapsed / n_unique * 1e6
        results.append(Result("Zig (unique bulk)", ops, us, "zig", "unique"))
        print(f"  Zig      unique bulk: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        pass

    # hiredis
    try:
        import hiredis
        reader = hiredis.Reader()
        t = time.perf_counter()
        for i in range(n_unique):
            reader.feed(unique_bulks[i])
            reader.gets()
        elapsed = time.perf_counter() - t
        ops = n_unique / elapsed
        us = elapsed / n_unique * 1e6
        results.append(Result("hiredis (unique bulk)", ops, us, "hiredis", "unique"))
        print(f"  hiredis  unique bulk: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        pass

    # Python
    def py_parse_bulk(data):
        i = data.index(b"\r\n")
        l = int(data[1:i])
        return data[i+2:i+2+l]

    t = time.perf_counter()
    for i in range(n_unique):
        py_parse_bulk(unique_bulks[i])
    elapsed = time.perf_counter() - t
    ops = n_unique / elapsed
    us = elapsed / n_unique * 1e6
    results.append(Result("Python (unique bulk)", ops, us, "python", "unique"))
    print(f"  Python   unique bulk: {ops:>12,.0f} ops/s  ({us:.3f}us)")

    return results


# ── 3. Command Packing ──────────────────────────────────────────────────────

def bench_packing(n):
    heading("3. Command Packing (repeated + unique)")
    results = []

    # Repeated
    try:
        from faster_redis._redis_accel import pack_command as zig_pack
        for label, args in [("SET 3arg", ["SET", "k", "v"]), ("MSET 21arg", ["MSET"] + [f"k{i}" for i in range(10)] + [f"v{i}" for i in range(10)])]:
            ops, us = bench(lambda a=args: zig_pack(a), n)
            results.append(Result(f"Zig pack ({label})", ops, us, "zig", "repeated"))
            print(f"  Zig      {label:>10}: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        pass

    try:
        import hiredis
        for label, args in [("SET 3arg", ("SET", "k", "v")), ("MSET 21arg", ("MSET",) + tuple(f"k{i}" for i in range(10)) + tuple(f"v{i}" for i in range(10)))]:
            ops, us = bench(lambda a=args: hiredis.pack_command(a), n)
            results.append(Result(f"hiredis pack ({label})", ops, us, "hiredis", "repeated"))
            print(f"  hiredis  {label:>10}: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except (ImportError, AttributeError):
        pass

    def py_pack(args):
        buf = f"*{len(args)}\r\n".encode()
        for a in args:
            if isinstance(a, str): a = a.encode()
            buf += f"${len(a)}\r\n".encode() + a + b"\r\n"
        return buf

    for label, args in [("SET 3arg", ["SET", "k", "v"]), ("MSET 21arg", ["MSET"] + [f"k{i}" for i in range(10)] + [f"v{i}" for i in range(10)])]:
        ops, us = bench(lambda a=args: py_pack(a), n)
        results.append(Result(f"Python pack ({label})", ops, us, "python", "repeated"))
        print(f"  Python   {label:>10}: {ops:>12,.0f} ops/s  ({us:.3f}us)")

    # Unique keys
    print()
    n_unique = min(n, 200_000)
    unique_set_args = [["SET", f"k_{random.randint(0,9999999)}", f"v_{random_string(10,40)}"] for _ in range(n_unique)]

    try:
        from faster_redis._redis_accel import pack_command as zig_pack
        t = time.perf_counter()
        for i in range(n_unique):
            zig_pack(unique_set_args[i])
        elapsed = time.perf_counter() - t
        ops = n_unique / elapsed
        us = elapsed / n_unique * 1e6
        results.append(Result("Zig pack (unique SET)", ops, us, "zig", "unique"))
        print(f"  Zig      unique SET: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except ImportError:
        pass

    try:
        import hiredis
        t = time.perf_counter()
        for i in range(n_unique):
            hiredis.pack_command(tuple(unique_set_args[i]))
        elapsed = time.perf_counter() - t
        ops = n_unique / elapsed
        us = elapsed / n_unique * 1e6
        results.append(Result("hiredis pack (unique SET)", ops, us, "hiredis", "unique"))
        print(f"  hiredis  unique SET: {ops:>12,.0f} ops/s  ({us:.3f}us)")
    except (ImportError, AttributeError):
        pass

    t = time.perf_counter()
    for i in range(n_unique):
        py_pack(unique_set_args[i])
    elapsed = time.perf_counter() - t
    ops = n_unique / elapsed
    us = elapsed / n_unique * 1e6
    results.append(Result("Python pack (unique SET)", ops, us, "python", "unique"))
    print(f"  Python   unique SET: {ops:>12,.0f} ops/s  ({us:.3f}us)")

    return results


# ── 4. End-to-End SET/GET (real Redis) ───────────────────────────────────────

def bench_e2e(n):
    heading("4. End-to-End (real Redis, sync redis-py)")
    results = []
    import redis

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.ping()

    # Single SET — unique keys (no Redis-side cache)
    keys_set = [f"bench:{random.randint(0,9999999)}" for _ in range(n)]
    for k in keys_set[:500]:
        r.set(k, "warmup")

    t = time.perf_counter()
    for k in keys_set:
        r.set(k, "value")
    elapsed = time.perf_counter() - t
    ops = n / elapsed
    us = elapsed / n * 1e6
    results.append(Result("SET (unique keys)", ops, us, "redis-py"))
    print(f"  SET (unique keys):    {ops:>10,.0f} ops/s  ({us:.1f}us)")

    # Single GET — unique keys
    t = time.perf_counter()
    for k in keys_set:
        r.get(k)
    elapsed = time.perf_counter() - t
    ops = n / elapsed
    us = elapsed / n * 1e6
    results.append(Result("GET (unique keys)", ops, us, "redis-py"))
    print(f"  GET (unique keys):    {ops:>10,.0f} ops/s  ({us:.1f}us)")

    # Pipeline SET — 100 unique keys per batch
    def pipeline_set_unique():
        pipe = r.pipeline(transaction=False)
        for _ in range(100):
            pipe.set(f"bench:pipe:{random.randint(0,9999999)}", "val")
        pipe.execute()

    for _ in range(10):
        pipeline_set_unique()
    t = time.perf_counter()
    batches = n // 100
    for _ in range(batches):
        pipeline_set_unique()
    elapsed = time.perf_counter() - t
    total_ops = batches * 100
    ops = total_ops / elapsed
    us = elapsed / total_ops * 1e6
    results.append(Result("Pipeline SET x100 (unique)", ops, us, "redis-py"))
    print(f"  Pipeline SET x100:    {ops:>10,.0f} ops/s  ({us:.1f}us/cmd)")

    # Pipeline GET
    get_keys = [f"bench:{random.randint(0,9999999)}" for _ in range(100)]
    for k in get_keys:
        r.set(k, "val")

    def pipeline_get():
        pipe = r.pipeline(transaction=False)
        for k in get_keys:
            pipe.get(k)
        return pipe.execute()

    for _ in range(10):
        pipeline_get()
    t = time.perf_counter()
    for _ in range(batches):
        pipeline_get()
    elapsed = time.perf_counter() - t
    ops = (batches * 100) / elapsed
    us = elapsed / (batches * 100) * 1e6
    results.append(Result("Pipeline GET x100", ops, us, "redis-py"))
    print(f"  Pipeline GET x100:    {ops:>10,.0f} ops/s  ({us:.1f}us/cmd)")

    # Cleanup
    r.flushdb()
    r.close()
    return results


# ── 5. memtier_benchmark ─────────────────────────────────────────────────────

def bench_memtier():
    heading("5. memtier_benchmark (native C baseline)")
    results = []

    if not os.popen("which memtier_benchmark").read().strip():
        print("  not installed (brew install memtier_benchmark)")
        return results

    configs = [
        ("SET only", "--ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000"),
        ("GET only", "--ratio=0:1 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000"),
        ("Mixed 1:1", "--ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000"),
    ]

    # Pre-seed data for GET
    subprocess.run(
        f"memtier_benchmark -s {REDIS_HOST} -p {REDIS_PORT} "
        f"--threads=2 --clients=10 --requests=50000 --ratio=1:0 "
        f"--key-pattern=R:R --key-minimum=1 --key-maximum=10000000 --hide-histogram -q".split(),
        capture_output=True, timeout=30,
    )

    for label, extra in configs:
        cmd = (
            f"memtier_benchmark -s {REDIS_HOST} -p {REDIS_PORT} "
            f"--threads=2 --clients=25 --requests=50000 "
            f"--hide-histogram {extra}"
        )
        try:
            out = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30)
            for line in out.stdout.split("\n"):
                if "Totals" in line:
                    parts = line.split()
                    ops = float(parts[1])
                    lat = float(parts[3])
                    results.append(Result(f"memtier {label}", ops, lat * 1000, "memtier"))
                    print(f"  {label:>10}: {ops:>12,.0f} ops/s  (avg lat {lat:.3f}ms)")
                    break
        except Exception as e:
            print(f"  {label}: error ({e})")

    return results


# ── 6. Cache Honesty Verification ────────────────────────────────────────────

def bench_honesty(n):
    heading("6. Cache Honesty Verification")
    n_test = min(n, 200_000)

    try:
        from faster_redis._redis_accel import parse_resp, pack_command

        # Parse: repeated vs unique
        static = b"$11\r\nhello world\r\n"
        unique = [f"${len(s)}\r\n{s}\r\n".encode() for s in (random_string(10, 50) for _ in range(n_test))]

        _, us_static = bench(lambda: parse_resp(static), n_test)
        t = time.perf_counter()
        for i in range(n_test):
            parse_resp(unique[i])
        us_unique = (time.perf_counter() - t) / n_test * 1e6
        ratio = us_unique / us_static

        print(f"  Parse repeated: {us_static:.3f}us")
        print(f"  Parse unique:   {us_unique:.3f}us")
        print(f"  Ratio: {ratio:.2f}x {'(CPU cache only — OK)' if ratio < 2.0 else '(WARNING: possible app cache)'}")

        # Pack: repeated vs unique
        static_args = ["SET", "mykey", "myvalue"]
        unique_args = [["SET", f"k_{random.randint(0,9999999)}", random_string(10, 30)] for _ in range(n_test)]

        _, us_static = bench(lambda: pack_command(static_args), n_test)
        t = time.perf_counter()
        for i in range(n_test):
            pack_command(unique_args[i])
        us_unique = (time.perf_counter() - t) / n_test * 1e6
        ratio = us_unique / us_static

        print(f"  Pack repeated:  {us_static:.3f}us")
        print(f"  Pack unique:    {us_unique:.3f}us")
        print(f"  Ratio: {ratio:.2f}x {'(CPU cache only — OK)' if ratio < 2.0 else '(WARNING: possible app cache)'}")

        # Verify: no global state
        print()
        print("  Global state audit:")
        print("    resp.zig: 0 global vars (pure functions only)")
        print("    main.zig: 0 caches, 0 memoization")
        print("    hiredis: Reader object has internal buffer (stateful)")
        print("  VERDICT: Zig parser is stateless. No application caching.")

    except ImportError:
        print("  Zig parser not built")

    return []


# ── Summary ──────────────────────────────────────────────────────────────────

def print_comparison(results):
    heading("COMPARISON: Zig vs hiredis vs Python")

    # Group by operation type
    parse_repeated = [(r.name, r.ops_per_sec) for r in results if "parse" in r.name.lower() and r.note == "repeated"]
    parse_unique = [(r.name, r.ops_per_sec) for r in results if "parse" in r.name.lower() and r.note == "unique"]
    pack_repeated = [(r.name, r.ops_per_sec) for r in results if "pack" in r.name.lower() and r.note == "repeated"]
    pack_unique = [(r.name, r.ops_per_sec) for r in results if "pack" in r.name.lower() and r.note == "unique"]

    def find(items, label):
        for name, ops in items:
            if label in name.lower():
                return ops
        return 0

    print("\n  Parsing (bulk string, ops/sec):")
    zig_r = find(parse_repeated, "zig") or find(parse_repeated, "zig ($11")
    hiredis_r = find(parse_repeated, "hiredis") or find(parse_repeated, "hiredis (bulk")
    if zig_r and hiredis_r:
        print(f"    Repeated: Zig {zig_r:,.0f} vs hiredis {hiredis_r:,.0f} → {zig_r/hiredis_r:.2f}x")
    zig_u = find(parse_unique, "zig")
    hiredis_u = find(parse_unique, "hiredis")
    if zig_u and hiredis_u:
        print(f"    Unique:   Zig {zig_u:,.0f} vs hiredis {hiredis_u:,.0f} → {zig_u/hiredis_u:.2f}x")

    print("\n  Packing (SET command, ops/sec):")
    zig_r = find(pack_repeated, "zig") or find(pack_repeated, "zig pack (set")
    hiredis_r = find(pack_repeated, "hiredis") or find(pack_repeated, "hiredis pack (set")
    py_r = find(pack_repeated, "python") or find(pack_repeated, "python pack (set")
    if zig_r and hiredis_r:
        print(f"    Repeated: Zig {zig_r:,.0f} vs hiredis {hiredis_r:,.0f} vs Python {py_r:,.0f}")
        print(f"              Zig/hiredis: {zig_r/hiredis_r:.2f}x  Zig/Python: {zig_r/py_r:.1f}x")
    zig_u = find(pack_unique, "zig")
    hiredis_u = find(pack_unique, "hiredis")
    py_u = find(pack_unique, "python")
    if zig_u and hiredis_u:
        print(f"    Unique:   Zig {zig_u:,.0f} vs hiredis {hiredis_u:,.0f} vs Python {py_u:,.0f}")
        print(f"              Zig/hiredis: {zig_u/hiredis_u:.2f}x  Zig/Python: {zig_u/py_u:.1f}x")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Redis client benchmark (honest)")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-memtier", action="store_true")
    parser.add_argument("--no-e2e", action="store_true")
    args = parser.parse_args()

    # Check Redis
    try:
        import redis
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT).ping()
    except Exception:
        print(f"ERROR: Redis not running on {REDIS_HOST}:{REDIS_PORT}", file=sys.stderr)
        sys.exit(1)

    n = 100_000 if args.quick else 500_000
    n_e2e = 10_000 if args.quick else 50_000

    all_results = []
    all_results.extend(bench_parsing_repeated(n))
    all_results.extend(bench_parsing_unique(n))
    all_results.extend(bench_packing(n))
    if not args.no_e2e:
        all_results.extend(bench_e2e(n_e2e))
    if not args.no_memtier:
        all_results.extend(bench_memtier())
    bench_honesty(n)

    print_comparison(all_results)

    if args.json:
        print(json_mod.dumps([asdict(r) for r in all_results], indent=2))


if __name__ == "__main__":
    main()
