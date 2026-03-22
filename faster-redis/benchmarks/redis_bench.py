#!/usr/bin/env python3
"""
redis-bench: faster-redis vs redis-py (+hiredis) vs redis.asyncio

Tests the real hot paths:
  1. RESP parsing speed (Zig SIMD vs hiredis C vs pure Python)
  2. Command packing speed (Zig vs Python string ops)
  3. End-to-end SET/GET (single, pipelined, async)
  4. memtier_benchmark via proxy (if available)

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


def heading(text):
    print(f"\n{'='*70}\n  {text}\n{'='*70}")


def bench(fn, n, warmup=500):
    for _ in range(warmup):
        fn()
    t = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = time.perf_counter() - t
    return n / elapsed, elapsed / n * 1e6


# ── 1. RESP Parsing Benchmark ───────────────────────────────────────────────

def bench_parsing(n=500_000):
    heading("RESP Parsing (parse response bytes)")
    results = []

    # Zig parser
    try:
        from faster_redis._redis_accel import parse_resp as zig_parse
        test_data = {
            "+OK": b"+OK\r\n",
            "$11 bulk": b"$11\r\nhello world\r\n",
            ":42 int": b":42\r\n",
            "*3 array": b"*3\r\n$3\r\nfoo\r\n$3\r\nbar\r\n:42\r\n",
        }
        for label, data in test_data.items():
            ops, us = bench(lambda d=data: zig_parse(d), n)
            results.append(Result(f"Zig parse ({label})", ops, us, "zig"))
            print(f"  Zig parse ({label:>10}): {ops:>12,.0f} ops/sec  ({us:.3f}us)")
    except ImportError:
        print("  Zig parser: not built")

    # hiredis parser
    try:
        import hiredis
        reader = hiredis.Reader()
        test_simple = b"+OK\r\n"
        test_bulk = b"$11\r\nhello world\r\n"
        test_array = b"*3\r\n$3\r\nfoo\r\n$3\r\nbar\r\n:42\r\n"

        def hiredis_parse(data):
            reader.feed(data)
            return reader.gets()

        for label, data in [("simple", test_simple), ("bulk", test_bulk), ("array", test_array)]:
            ops, us = bench(lambda d=data: hiredis_parse(d), n)
            results.append(Result(f"hiredis parse ({label})", ops, us, "hiredis"))
            print(f"  hiredis    ({label:>10}): {ops:>12,.0f} ops/sec  ({us:.3f}us)")
    except ImportError:
        print("  hiredis: not installed (pip install hiredis)")

    # Pure Python parser
    def py_parse_simple(data):
        return data[1:data.index(b"\r\n")].decode()

    def py_parse_bulk(data):
        i = data.index(b"\r\n")
        length = int(data[1:i])
        return data[i + 2:i + 2 + length]

    ops_s, us_s = bench(lambda: py_parse_simple(b"+OK\r\n"), n)
    ops_b, us_b = bench(lambda: py_parse_bulk(b"$11\r\nhello world\r\n"), n)
    results.append(Result("Python parse (simple)", ops_s, us_s, "python"))
    results.append(Result("Python parse (bulk)", ops_b, us_b, "python"))
    print(f"  Python     ({'simple':>10}): {ops_s:>12,.0f} ops/sec  ({us_s:.3f}us)")
    print(f"  Python     ({'bulk':>10}): {ops_b:>12,.0f} ops/sec  ({us_b:.3f}us)")

    return results


# ── 2. Command Packing Benchmark ────────────────────────────────────────────

def bench_packing(n=500_000):
    heading("Command Packing (serialize command to RESP)")
    results = []

    # Zig packer
    try:
        from faster_redis._redis_accel import pack_command as zig_pack
        for label, args in [("SET", ["SET", "k", "v"]), ("MSET 10", ["MSET"] + [f"k{i}" for i in range(10)] + [f"v{i}" for i in range(10)])]:
            ops, us = bench(lambda a=args: zig_pack(a), n)
            results.append(Result(f"Zig pack ({label})", ops, us, "zig"))
            print(f"  Zig pack   ({label:>8}): {ops:>12,.0f} ops/sec  ({us:.3f}us)")
    except ImportError:
        print("  Zig packer: not built")

    # hiredis packer
    try:
        import hiredis
        for label, args in [("SET", ("SET", "k", "v")), ("MSET 10", ("MSET",) + tuple(f"k{i}" for i in range(10)) + tuple(f"v{i}" for i in range(10)))]:
            ops, us = bench(lambda a=args: hiredis.pack_command(a), n)
            results.append(Result(f"hiredis pack ({label})", ops, us, "hiredis"))
            print(f"  hiredis    ({label:>8}): {ops:>12,.0f} ops/sec  ({us:.3f}us)")
    except (ImportError, AttributeError):
        print("  hiredis packer: not available")

    # Python packer
    def py_pack(args):
        buf = f"*{len(args)}\r\n".encode()
        for a in args:
            if isinstance(a, str):
                a = a.encode()
            buf += f"${len(a)}\r\n".encode() + a + b"\r\n"
        return buf

    for label, args in [("SET", ["SET", "k", "v"]), ("MSET 10", ["MSET"] + [f"k{i}" for i in range(10)] + [f"v{i}" for i in range(10)])]:
        ops, us = bench(lambda a=args: py_pack(a), n)
        results.append(Result(f"Python pack ({label})", ops, us, "python"))
        print(f"  Python     ({label:>8}): {ops:>12,.0f} ops/sec  ({us:.3f}us)")

    return results


# ── 3. End-to-End SET/GET ────────────────────────────────────────────────────

def bench_e2e_sync(n=50_000):
    heading("End-to-End SET/GET (sync, redis-py)")
    results = []

    import redis

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.ping()

    # Single SET
    ops, us = bench(lambda: r.set("bench:key", "value"), n)
    results.append(Result("redis-py SET", ops, us, "redis-py"))
    print(f"  redis-py SET:         {ops:>10,.0f} ops/sec  ({us:.1f}us)")

    # Single GET
    r.set("bench:key", "value")
    ops, us = bench(lambda: r.get("bench:key"), n)
    results.append(Result("redis-py GET", ops, us, "redis-py"))
    print(f"  redis-py GET:         {ops:>10,.0f} ops/sec  ({us:.1f}us)")

    # Pipeline SET x100
    def pipeline_set():
        pipe = r.pipeline(transaction=False)
        for i in range(100):
            pipe.set(f"bench:pipe:{i}", f"val{i}")
        pipe.execute()

    ops, us = bench(pipeline_set, n // 100)
    results.append(Result("redis-py pipeline SET x100", ops * 100, us / 100, "redis-py"))
    print(f"  redis-py pipeline SET (x100): {ops*100:>7,.0f} ops/sec  ({us/100:.1f}us/cmd)")

    # Pipeline GET x100
    for i in range(100):
        r.set(f"bench:pipe:{i}", f"val{i}")

    def pipeline_get():
        pipe = r.pipeline(transaction=False)
        for i in range(100):
            pipe.get(f"bench:pipe:{i}")
        return pipe.execute()

    ops, us = bench(pipeline_get, n // 100)
    results.append(Result("redis-py pipeline GET x100", ops * 100, us / 100, "redis-py"))
    print(f"  redis-py pipeline GET (x100): {ops*100:>7,.0f} ops/sec  ({us/100:.1f}us/cmd)")

    # Cleanup
    r.delete(*[f"bench:pipe:{i}" for i in range(100)], "bench:key")
    r.close()

    return results


# ── 4. End-to-End Async ──────────────────────────────────────────────────────

def bench_e2e_async(n=50_000):
    heading("End-to-End SET/GET (async, redis.asyncio)")
    results = []

    async def run():
        from redis import asyncio as aioredis
        r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        await r.ping()

        # Async SET
        t = time.perf_counter()
        for _ in range(n):
            await r.set("bench:akey", "value")
        elapsed = time.perf_counter() - t
        ops = n / elapsed
        us = elapsed / n * 1e6
        results.append(Result("async SET", ops, us, "async"))
        print(f"  async SET:            {ops:>10,.0f} ops/sec  ({us:.1f}us)")

        # Async GET
        await r.set("bench:akey", "value")
        t = time.perf_counter()
        for _ in range(n):
            await r.get("bench:akey")
        elapsed = time.perf_counter() - t
        ops = n / elapsed
        us = elapsed / n * 1e6
        results.append(Result("async GET", ops, us, "async"))
        print(f"  async GET:            {ops:>10,.0f} ops/sec  ({us:.1f}us)")

        # Async pipeline
        async def async_pipeline():
            pipe = r.pipeline(transaction=False)
            for i in range(100):
                pipe.set(f"bench:apipe:{i}", f"val{i}")
            await pipe.execute()

        t = time.perf_counter()
        for _ in range(n // 100):
            await async_pipeline()
        elapsed = time.perf_counter() - t
        ops = n / elapsed
        us = elapsed / n * 1e6
        results.append(Result("async pipeline SET x100", ops, us / 100, "async"))
        print(f"  async pipeline SET (x100): {ops:>7,.0f} ops/sec  ({us/100:.1f}us/cmd)")

        await r.delete(*[f"bench:apipe:{i}" for i in range(100)], "bench:akey")
        await r.aclose()

    asyncio.run(run())
    return results


# ── 5. memtier_benchmark ─────────────────────────────────────────────────────

def bench_memtier():
    heading("memtier_benchmark (native C, baseline)")
    results = []

    if not os.popen("which memtier_benchmark").read().strip():
        print("  memtier_benchmark not found (brew install memtier_benchmark)")
        return results

    for label, args in [
        ("SET only", "--ratio=1:0 --key-pattern=S:S"),
        ("GET only", "--ratio=0:1 --key-pattern=S:S --key-minimum=1 --key-maximum=1000"),
        ("Mixed 1:1", "--ratio=1:1 --key-pattern=S:S"),
    ]:
        cmd = (
            f"memtier_benchmark -s {REDIS_HOST} -p {REDIS_PORT} "
            f"--threads=4 --clients=50 --requests=100000 "
            f"--hide-histogram {args}"
        )
        try:
            out = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=60)
            # Parse "Totals" line
            for line in out.stdout.split("\n"):
                if "Totals" in line:
                    parts = line.split()
                    # Totals   ops/sec   hits/sec   misses/sec  avg_latency  ...
                    ops = float(parts[1])
                    lat = float(parts[3])
                    results.append(Result(f"memtier {label}", ops, lat * 1000, "memtier"))
                    print(f"  memtier {label:>10}: {ops:>12,.0f} ops/sec  ({lat:.3f}ms avg lat)")
                    break
        except Exception as e:
            print(f"  memtier {label}: error ({e})")

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Redis client benchmark")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-memtier", action="store_true")
    args = parser.parse_args()

    # Check Redis
    import redis
    try:
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT).ping()
    except Exception:
        print(f"ERROR: Redis not running on {REDIS_HOST}:{REDIS_PORT}", file=sys.stderr)
        sys.exit(1)

    n_parse = 100_000 if args.quick else 500_000
    n_e2e = 10_000 if args.quick else 50_000

    all_results = []
    all_results.extend(bench_parsing(n_parse))
    all_results.extend(bench_packing(n_parse))
    all_results.extend(bench_e2e_sync(n_e2e))
    all_results.extend(bench_e2e_async(n_e2e))
    if not args.no_memtier:
        all_results.extend(bench_memtier())

    if args.json:
        print(json_mod.dumps([asdict(r) for r in all_results], indent=2))
    else:
        # Summary table
        heading("Summary")
        fmt = "{:<35} {:>12} {:>10} {:>8}"
        print(fmt.format("Operation", "ops/sec", "latency", "client"))
        print(fmt.format("-" * 35, "-" * 12, "-" * 10, "-" * 8))
        for r in all_results:
            print(fmt.format(r.name, f"{r.ops_per_sec:,.0f}", f"{r.us_per_op:.1f}us", r.label))


if __name__ == "__main__":
    main()
