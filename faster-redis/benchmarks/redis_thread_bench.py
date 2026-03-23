#!/usr/bin/env python3
"""Multithread benchmark for redis-py vs faster-redis under free-threaded Python."""

from __future__ import annotations

import argparse
import random
import threading
import time

import redis

from faster_redis import PooledRedis
from faster_redis import Redis as FastRedis
from faster_redis import ThreadLocalRedis

def heading(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_threads(label, worker_factory, num_threads, batches, batch_size):
    start_barrier = threading.Barrier(num_threads + 1)
    done_barrier = threading.Barrier(num_threads + 1)
    errors = []

    def runner():
        try:
            worker = worker_factory()
            start_barrier.wait()
            worker()
            done_barrier.wait()
        except Exception as exc:  # pragma: no cover - benchmark path
            errors.append(exc)

    threads = [threading.Thread(target=runner) for _ in range(num_threads)]
    for thread in threads:
        thread.start()
    start_barrier.wait()
    t0 = time.perf_counter()
    done_barrier.wait()
    elapsed = time.perf_counter() - t0
    for thread in threads:
        thread.join()

    if errors:
        raise RuntimeError(f"{label} worker failed: {errors[0]}")

    total_ops = num_threads * batches * batch_size
    ops = total_ops / elapsed
    us = elapsed / total_ops * 1e6
    print(f"  {label:<30} {ops:>12,.0f} ops/s  ({us:.2f}us/op)")
    return ops


def main():
    parser = argparse.ArgumentParser(description="Threaded Redis benchmark")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batches", type=int, default=250)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--pool-size", type=int, default=4)
    args = parser.parse_args()

    server = redis.Redis(host=args.host, port=args.port, decode_responses=True)
    server.ping()
    server.flushdb()

    heading("Multithread Pipeline Benchmark")
    print(f"Threads: {args.threads}  Batches/thread: {args.batches}  Batch size: {args.batch_size}")

    repeated_keys = [f"thread:get:{i}" for i in range(args.batch_size)]
    for key in repeated_keys:
        server.set(key, "v")

    shared_fast = FastRedis(host=args.host, port=args.port)
    tls_fast = ThreadLocalRedis(host=args.host, port=args.port)
    pooled_fast = PooledRedis(size=args.pool_size, host=args.host, port=args.port)

    def py_worker_factory():
        client = redis.Redis(host=args.host, port=args.port, decode_responses=True)

        def run():
            for _ in range(args.batches):
                pipe = client.pipeline(transaction=False)
                for key in repeated_keys:
                    pipe.get(key)
                pipe.execute()
            client.close()

        return run

    def shared_fast_worker_factory():
        def run():
            for _ in range(args.batches):
                pipe = shared_fast.pipeline(transaction=False)
                for key in repeated_keys:
                    pipe.get(key)
                pipe.execute()

        return run

    def tls_fast_worker_factory():
        def run():
            client = tls_fast.client()
            for _ in range(args.batches):
                pipe = client.pipeline(transaction=False)
                for key in repeated_keys:
                    pipe.get(key)
                pipe.execute()
            tls_fast.close_thread()

        return run

    def pooled_fast_worker_factory():
        def run():
            for _ in range(args.batches):
                with pooled_fast.connection() as client:
                    pipe = client.pipeline(transaction=False)
                    for key in repeated_keys:
                        pipe.get(key)
                    pipe.execute()

        return run

    py_get = run_threads("redis-py GET x100", py_worker_factory, args.threads, args.batches, args.batch_size)
    shared_fast_get = run_threads(
        "faster-redis shared GET x100",
        shared_fast_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )
    tls_fast_get = run_threads(
        "faster-redis TLS GET x100",
        tls_fast_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )
    pooled_fast_get = run_threads(
        "faster-redis pool GET x100",
        pooled_fast_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )

    def py_set_worker_factory():
        client = redis.Redis(host=args.host, port=args.port, decode_responses=True)

        def run():
            for _ in range(args.batches):
                pipe = client.pipeline(transaction=False)
                for _ in range(args.batch_size):
                    pipe.set(f"py:set:{threading.get_ident()}:{random.randint(0, 10_000_000)}", "v")
                pipe.execute()
            client.close()

        return run

    def shared_fast_set_worker_factory():
        def run():
            for _ in range(args.batches):
                pipe = shared_fast.pipeline(transaction=False)
                for _ in range(args.batch_size):
                    pipe.set(f"fast:shared:set:{threading.get_ident()}:{random.randint(0, 10_000_000)}", "v")
                pipe.execute()

        return run

    def tls_fast_set_worker_factory():
        def run():
            client = tls_fast.client()
            for _ in range(args.batches):
                pipe = client.pipeline(transaction=False)
                for _ in range(args.batch_size):
                    pipe.set(f"fast:tls:set:{threading.get_ident()}:{random.randint(0, 10_000_000)}", "v")
                pipe.execute()
            tls_fast.close_thread()

        return run

    def pooled_fast_set_worker_factory():
        def run():
            for _ in range(args.batches):
                with pooled_fast.connection() as client:
                    pipe = client.pipeline(transaction=False)
                    for _ in range(args.batch_size):
                        pipe.set(f"fast:pool:set:{threading.get_ident()}:{random.randint(0, 10_000_000)}", "v")
                    pipe.execute()

        return run

    print()
    py_set = run_threads("redis-py SET x100", py_set_worker_factory, args.threads, args.batches, args.batch_size)
    shared_fast_set = run_threads(
        "faster-redis shared SET x100",
        shared_fast_set_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )
    tls_fast_set = run_threads(
        "faster-redis TLS SET x100",
        tls_fast_set_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )
    pooled_fast_set = run_threads(
        "faster-redis pool SET x100",
        pooled_fast_set_worker_factory,
        args.threads,
        args.batches,
        args.batch_size,
    )

    print()
    print("Summary:")
    print(
        f"  GET speedup vs redis-py: shared {shared_fast_get / py_get:.2f}x, "
        f"TLS {tls_fast_get / py_get:.2f}x, pool {pooled_fast_get / py_get:.2f}x"
    )
    print(
        f"  SET speedup vs redis-py: shared {shared_fast_set / py_set:.2f}x, "
        f"TLS {tls_fast_set / py_set:.2f}x, pool {pooled_fast_set / py_set:.2f}x"
    )
    print(
        f"  TLS vs shared faster-redis: GET {tls_fast_get / shared_fast_get:.2f}x, "
        f"SET {tls_fast_set / shared_fast_set:.2f}x"
    )
    print(
        f"  Pool vs shared faster-redis: GET {pooled_fast_get / shared_fast_get:.2f}x, "
        f"SET {pooled_fast_set / shared_fast_set:.2f}x"
    )

    shared_fast.close()
    tls_fast.close()
    pooled_fast.close()
    server.close()


if __name__ == "__main__":
    main()
