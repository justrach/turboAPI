#!/usr/bin/env python3
"""
TurboAPI Performance Benchmark Suite

Tests actual framework performance including:
- Sync vs Async handler dispatch
- JSON serialization
- Concurrent request handling
- Route matching speed
"""

import asyncio
import json
import time
import threading
import concurrent.futures
from typing import Any
import statistics

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

from turboapi import TurboAPI


class BenchmarkResults:
    """Collects and reports benchmark results"""

    def __init__(self):
        self.results = {}

    def add(self, name: str, times: list[float], unit: str = "ms"):
        """Add benchmark result with timing data"""
        if not times:
            return
        self.results[name] = {
            "mean": statistics.mean(times),
            "median": statistics.median(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            "min": min(times),
            "max": max(times),
            "samples": len(times),
            "unit": unit
        }

    def report(self):
        """Print formatted benchmark report"""
        print("\n" + "=" * 80)
        print(" TURBOAPI PERFORMANCE BENCHMARK RESULTS")
        print("=" * 80)

        for name, data in self.results.items():
            print(f"\n{name}")
            print("-" * len(name))
            print(f"  Mean:   {data['mean']:.3f} {data['unit']}")
            print(f"  Median: {data['median']:.3f} {data['unit']}")
            print(f"  StdDev: {data['stdev']:.3f} {data['unit']}")
            print(f"  Min:    {data['min']:.3f} {data['unit']}")
            print(f"  Max:    {data['max']:.3f} {data['unit']}")
            print(f"  Samples: {data['samples']}")

        print("\n" + "=" * 80)


def benchmark_json_serialization():
    """Benchmark JSON serialization speeds"""
    results = BenchmarkResults()

    # Test payloads
    small = {"status": "ok", "message": "Hello", "id": 123}
    medium = {"data": [{"id": i, "name": f"item_{i}", "active": i % 2 == 0} for i in range(50)]}
    large = {
        "users": [
            {
                "id": i,
                "name": f"User {i}",
                "email": f"user{i}@example.com",
                "profile": {"bio": "Lorem ipsum", "settings": {"theme": "dark"}},
                "posts": [{"id": j, "title": f"Post {j}"} for j in range(10)]
            }
            for i in range(100)
        ]
    }

    iterations = 10000

    # Small payload
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        json.dumps(small)
        times.append((time.perf_counter() - start) * 1000)
    results.add("JSON Serialize (small - 3 keys)", times, "ms")

    # Medium payload
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        json.dumps(medium)
        times.append((time.perf_counter() - start) * 1000)
    results.add("JSON Serialize (medium - 50 items)", times, "ms")

    # Large payload
    times = []
    for _ in range(iterations // 10):
        start = time.perf_counter()
        json.dumps(large)
        times.append((time.perf_counter() - start) * 1000)
    results.add("JSON Serialize (large - 100 users)", times, "ms")

    return results


def benchmark_handler_dispatch():
    """Benchmark sync vs async handler dispatch"""
    results = BenchmarkResults()
    iterations = 10000

    # Sync handler simulation
    def sync_handler():
        data = [1, 2, 3, 4, 5]
        result = sum(data)
        return {"result": result}

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        sync_handler()
        times.append((time.perf_counter() - start) * 1000)
    results.add("Sync Handler Dispatch", times, "ms")

    # Async handler simulation
    async def async_handler():
        data = [1, 2, 3, 4, 5]
        result = sum(data)
        return {"result": result}

    async def run_async():
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            await async_handler()
            times.append((time.perf_counter() - start) * 1000)
        return times

    times = asyncio.run(run_async())
    results.add("Async Handler Dispatch", times, "ms")

    # Async with task spawn
    async def run_async_spawn():
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            await asyncio.create_task(async_handler())
            times.append((time.perf_counter() - start) * 1000)
        return times

    times = asyncio.run(run_async_spawn())
    results.add("Async Handler + Task Spawn", times, "ms")

    return results


def benchmark_concurrent_tasks():
    """Benchmark concurrent task handling"""
    results = BenchmarkResults()

    async def worker(n: int):
        await asyncio.sleep(0)
        return n * 2

    async def run_concurrent(count: int):
        start = time.perf_counter()
        tasks = [asyncio.create_task(worker(i)) for i in range(count)]
        await asyncio.gather(*tasks)
        return (time.perf_counter() - start) * 1000

    for count in [10, 50, 100, 500, 1000]:
        times = []
        for _ in range(100):
            time_ms = asyncio.run(run_concurrent(count))
            times.append(time_ms)
        results.add(f"Spawn & Await {count} Tasks", times, "ms")

    return results


def benchmark_route_matching():
    """Benchmark route key creation and matching"""
    results = BenchmarkResults()
    iterations = 100000

    # Simple route key creation
    paths = [
        "/",
        "/api/users",
        "/api/v1/users/123/posts",
        "/api/v1/organizations/abc-def-123/projects/xyz-789/tasks/456/comments"
    ]

    for path in paths:
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            route_key = f"GET {path}"
            times.append((time.perf_counter() - start) * 1000000)  # microseconds
        results.add(f"Route Key '{path[:30]}...'", times, "µs")

    # Dictionary lookup simulation
    routes = {f"GET {path}": lambda: None for path in paths}

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        handler = routes.get("GET /api/v1/users/123/posts")
        times.append((time.perf_counter() - start) * 1000000)
    results.add("Route Dict Lookup", times, "µs")

    return results


def benchmark_live_server():
    """Benchmark actual HTTP requests to TurboAPI server"""
    results = BenchmarkResults()

    # Create test app
    app = TurboAPI(title="Benchmark Server")
    app.configure_rate_limiting(enabled=False)

    @app.get("/sync")
    def sync_endpoint():
        return {"type": "sync", "data": [1, 2, 3, 4, 5]}

    @app.get("/async")
    async def async_endpoint():
        return {"type": "async", "data": [1, 2, 3, 4, 5]}

    @app.get("/json/small")
    def json_small():
        return {"status": "ok", "id": 123}

    @app.get("/json/medium")
    def json_medium():
        return {"data": [{"id": i, "name": f"item_{i}"} for i in range(50)]}

    @app.get("/json/large")
    def json_large():
        return {
            "users": [
                {
                    "id": i,
                    "name": f"User {i}",
                    "posts": [{"id": j, "title": f"Post {j}"} for j in range(10)]
                }
                for i in range(100)
            ]
        }

    # Start server in background
    port = 9876
    server_thread = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    server_thread.start()
    time.sleep(2)  # Wait for server to start

    base_url = f"http://127.0.0.1:{port}"
    iterations = 500
    warmup = 50

    try:
        # Warmup
        for _ in range(warmup):
            requests.get(f"{base_url}/sync", timeout=5)

        # Sync endpoint
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            resp = requests.get(f"{base_url}/sync", timeout=5)
            times.append((time.perf_counter() - start) * 1000)
        results.add("HTTP GET /sync", times, "ms")

        # Async endpoint
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            resp = requests.get(f"{base_url}/async", timeout=5)
            times.append((time.perf_counter() - start) * 1000)
        results.add("HTTP GET /async", times, "ms")

        # JSON payloads
        for endpoint in ["/json/small", "/json/medium", "/json/large"]:
            times = []
            for _ in range(iterations // 5):
                start = time.perf_counter()
                resp = requests.get(f"{base_url}{endpoint}", timeout=5)
                times.append((time.perf_counter() - start) * 1000)
            results.add(f"HTTP GET {endpoint}", times, "ms")

        # Concurrent requests
        for concurrency in [10, 50, 100]:
            def make_request():
                start = time.perf_counter()
                requests.get(f"{base_url}/sync", timeout=5)
                return (time.perf_counter() - start) * 1000

            times = []
            for _ in range(10):  # 10 batches
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                    batch_start = time.perf_counter()
                    futures = [executor.submit(make_request) for _ in range(concurrency)]
                    concurrent.futures.wait(futures)
                    batch_time = (time.perf_counter() - batch_start) * 1000
                    times.append(batch_time)
            results.add(f"Concurrent {concurrency} requests (batch)", times, "ms")

    except Exception as e:
        print(f"Error during live server benchmark: {e}")

    return results


def run_all_benchmarks():
    """Run all benchmark suites"""
    print("\n" + "=" * 80)
    print(" TURBOAPI PERFORMANCE BENCHMARK SUITE")
    print("=" * 80)
    print("\nRunning benchmarks... This may take a few minutes.\n")

    all_results = BenchmarkResults()

    # Run each benchmark suite
    print("[1/5] JSON Serialization...")
    json_results = benchmark_json_serialization()
    all_results.results.update(json_results.results)

    print("[2/5] Handler Dispatch...")
    dispatch_results = benchmark_handler_dispatch()
    all_results.results.update(dispatch_results.results)

    print("[3/5] Concurrent Tasks...")
    concurrent_results = benchmark_concurrent_tasks()
    all_results.results.update(concurrent_results.results)

    print("[4/5] Route Matching...")
    route_results = benchmark_route_matching()
    all_results.results.update(route_results.results)

    print("[5/5] Live Server (HTTP)...")
    server_results = benchmark_live_server()
    all_results.results.update(server_results.results)

    # Print final report
    all_results.report()

    # Summary
    print("\nKEY INSIGHTS:")
    print("-" * 40)

    if "HTTP GET /sync" in all_results.results and "HTTP GET /async" in all_results.results:
        sync_mean = all_results.results["HTTP GET /sync"]["mean"]
        async_mean = all_results.results["HTTP GET /async"]["mean"]
        diff = ((async_mean - sync_mean) / sync_mean) * 100
        print(f"  Async vs Sync overhead: {diff:+.1f}%")

    if "Sync Handler Dispatch" in all_results.results and "Async Handler Dispatch" in all_results.results:
        sync_mean = all_results.results["Sync Handler Dispatch"]["mean"]
        async_mean = all_results.results["Async Handler Dispatch"]["mean"]
        print(f"  Pure handler dispatch - Sync: {sync_mean:.4f}ms, Async: {async_mean:.4f}ms")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    run_all_benchmarks()
