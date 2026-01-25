#!/usr/bin/env python3
"""
Request Throughput Benchmark: TurboAPI vs FastAPI

Measures requests per second using test clients.
"""

import time
import json
from dataclasses import dataclass
from typing import Optional

# Import frameworks
try:
    from turboapi import TurboAPI
    from turboapi.testclient import TestClient as TurboTestClient
    HAS_TURBOAPI = True
except ImportError:
    HAS_TURBOAPI = False

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient as FastAPITestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# Import validation libraries for models
import dhi
import pydantic


@dataclass
class ThroughputResult:
    name: str
    turbo_rps: float
    fastapi_rps: float
    speedup: float
    iterations: int


def main():
    print("=" * 70)
    print("Request Throughput Benchmark: TurboAPI vs FastAPI")
    print("=" * 70)
    print()

    if not HAS_TURBOAPI:
        print("TurboAPI not available. Install with: pip install turboapi")
        return

    if not HAS_FASTAPI:
        print("FastAPI not available. Install with: pip install fastapi")
        return

    print(f"dhi version: {dhi.__version__}")
    print(f"pydantic version: {pydantic.__version__}")
    print()

    results = []
    ITERATIONS = 10_000

    # ================================================================
    # Setup TurboAPI app
    # ================================================================
    turbo_app = TurboAPI()

    class TurboItem(dhi.BaseModel):
        name: str
        price: float
        quantity: int = 1

    @turbo_app.get("/")
    def turbo_root():
        return {"message": "Hello World"}

    @turbo_app.get("/items/{item_id}")
    def turbo_get_item(item_id: int):
        return {"item_id": item_id, "name": "Test Item"}

    @turbo_app.post("/items")
    def turbo_create_item(item: TurboItem):
        return {"item": item.model_dump(), "created": True}

    turbo_client = TurboTestClient(turbo_app)

    # ================================================================
    # Setup FastAPI app
    # ================================================================
    fastapi_app = FastAPI()

    class FastAPIItem(pydantic.BaseModel):
        name: str
        price: float
        quantity: int = 1

    @fastapi_app.get("/")
    def fastapi_root():
        return {"message": "Hello World"}

    @fastapi_app.get("/items/{item_id}")
    def fastapi_get_item(item_id: int):
        return {"item_id": item_id, "name": "Test Item"}

    @fastapi_app.post("/items")
    def fastapi_create_item(item: FastAPIItem):
        return {"item": item.model_dump(), "created": True}

    fastapi_client = FastAPITestClient(fastapi_app)

    # ================================================================
    # Test 1: Simple GET Request
    # ================================================================
    print("Running benchmarks...")
    print()

    # Warmup
    for _ in range(100):
        turbo_client.get("/")
        fastapi_client.get("/")

    # Benchmark TurboAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        turbo_client.get("/")
    turbo_time = time.perf_counter() - start
    turbo_rps = ITERATIONS / turbo_time

    # Benchmark FastAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        fastapi_client.get("/")
    fastapi_time = time.perf_counter() - start
    fastapi_rps = ITERATIONS / fastapi_time

    results.append(ThroughputResult(
        name="GET /",
        turbo_rps=turbo_rps,
        fastapi_rps=fastapi_rps,
        speedup=turbo_rps / fastapi_rps if fastapi_rps > 0 else 0,
        iterations=ITERATIONS,
    ))

    # ================================================================
    # Test 2: GET with Path Parameter
    # ================================================================
    # Warmup
    for _ in range(100):
        turbo_client.get("/items/123")
        fastapi_client.get("/items/123")

    # Benchmark TurboAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        turbo_client.get("/items/123")
    turbo_time = time.perf_counter() - start
    turbo_rps = ITERATIONS / turbo_time

    # Benchmark FastAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        fastapi_client.get("/items/123")
    fastapi_time = time.perf_counter() - start
    fastapi_rps = ITERATIONS / fastapi_time

    results.append(ThroughputResult(
        name="GET /items/{id}",
        turbo_rps=turbo_rps,
        fastapi_rps=fastapi_rps,
        speedup=turbo_rps / fastapi_rps if fastapi_rps > 0 else 0,
        iterations=ITERATIONS,
    ))

    # ================================================================
    # Test 3: POST with JSON Body
    # ================================================================
    item_data = {"name": "Widget", "price": 9.99, "quantity": 5}

    # Warmup
    for _ in range(100):
        turbo_client.post("/items", json=item_data)
        fastapi_client.post("/items", json=item_data)

    # Benchmark TurboAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        turbo_client.post("/items", json=item_data)
    turbo_time = time.perf_counter() - start
    turbo_rps = ITERATIONS / turbo_time

    # Benchmark FastAPI
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        fastapi_client.post("/items", json=item_data)
    fastapi_time = time.perf_counter() - start
    fastapi_rps = ITERATIONS / fastapi_time

    results.append(ThroughputResult(
        name="POST /items",
        turbo_rps=turbo_rps,
        fastapi_rps=fastapi_rps,
        speedup=turbo_rps / fastapi_rps if fastapi_rps > 0 else 0,
        iterations=ITERATIONS,
    ))

    # ================================================================
    # Print Results
    # ================================================================
    print("=" * 70)
    print(f"{'Endpoint':<20} {'TurboAPI':>12} {'FastAPI':>12} {'Speedup':>10}")
    print("-" * 70)

    for r in results:
        print(f"{r.name:<20} {r.turbo_rps:>10.0f}/s {r.fastapi_rps:>10.0f}/s {r.speedup:>9.1f}x")

    print("=" * 70)
    print()

    avg_speedup = sum(r.speedup for r in results) / len(results) if results else 0
    print(f"Average speedup: {avg_speedup:.1f}x faster than FastAPI")
    print()
    print("Note: Test client benchmarks measure framework overhead.")
    print("Real-world HTTP benchmarks may show different results.")


if __name__ == "__main__":
    main()
