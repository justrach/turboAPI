#!/usr/bin/env python3
"""
JSON Serialization Benchmark: dhi vs Pydantic

Compares JSON encoding/decoding performance.
"""

import time
import json
from dataclasses import dataclass
from typing import List

import dhi
import pydantic


@dataclass
class JSONResult:
    name: str
    dhi_time_ms: float
    pydantic_time_ms: float
    speedup: float


def run_benchmark(name: str, dhi_func, pydantic_func, iterations: int = 50_000) -> JSONResult:
    """Run a benchmark comparing dhi vs pydantic."""
    # Warmup
    for _ in range(min(1000, iterations // 10)):
        dhi_func()
        pydantic_func()

    # Benchmark dhi
    start = time.perf_counter()
    for _ in range(iterations):
        dhi_func()
    dhi_time = (time.perf_counter() - start) * 1000

    # Benchmark pydantic
    start = time.perf_counter()
    for _ in range(iterations):
        pydantic_func()
    pydantic_time = (time.perf_counter() - start) * 1000

    speedup = pydantic_time / dhi_time if dhi_time > 0 else 0

    return JSONResult(
        name=name,
        dhi_time_ms=dhi_time,
        pydantic_time_ms=pydantic_time,
        speedup=speedup,
    )


def main():
    print("=" * 70)
    print("JSON Serialization Benchmark: dhi vs Pydantic")
    print("=" * 70)
    print()
    print(f"dhi version: {dhi.__version__} (native={dhi.HAS_NATIVE_EXT})")
    print(f"pydantic version: {pydantic.__version__}")
    print()

    results: List[JSONResult] = []
    ITERATIONS = 50_000

    # ================================================================
    # Test 1: Simple Model to JSON
    # ================================================================
    class DhiUser(dhi.BaseModel):
        id: int
        name: str
        email: str
        active: bool = True

    class PydanticUser(pydantic.BaseModel):
        id: int
        name: str
        email: str
        active: bool = True

    dhi_user = DhiUser(id=1, name="Alice", email="alice@example.com")
    pydantic_user = PydanticUser(id=1, name="Alice", email="alice@example.com")

    result = run_benchmark(
        "model_dump_json()",
        lambda: dhi_user.model_dump_json(),
        lambda: pydantic_user.model_dump_json(),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 2: model_dump() + json.dumps()
    # ================================================================
    result = run_benchmark(
        "dump + json.dumps",
        lambda: json.dumps(dhi_user.model_dump()),
        lambda: json.dumps(pydantic_user.model_dump()),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 3: JSON to Model (parse JSON string)
    # ================================================================
    json_str = '{"id": 1, "name": "Alice", "email": "alice@example.com", "active": true}'

    # dhi uses json.loads + model_validate, Pydantic has native model_validate_json
    result = run_benchmark(
        "JSON string to model",
        lambda: DhiUser.model_validate(json.loads(json_str)),
        lambda: PydanticUser.model_validate_json(json_str),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 4: Complex Nested JSON
    # ================================================================
    class DhiOrder(dhi.BaseModel):
        id: int
        customer: str
        items: list = []
        total: float = 0.0

    class PydanticOrder(pydantic.BaseModel):
        id: int
        customer: str
        items: list = []
        total: float = 0.0

    order_data = {
        "id": 123,
        "customer": "Bob Smith",
        "items": [
            {"name": "Widget", "price": 9.99, "qty": 2},
            {"name": "Gadget", "price": 19.99, "qty": 1},
            {"name": "Thing", "price": 4.99, "qty": 5},
        ],
        "total": 64.92,
    }

    dhi_order = DhiOrder(**order_data)
    pydantic_order = PydanticOrder(**order_data)

    result = run_benchmark(
        "Nested JSON dump",
        lambda: dhi_order.model_dump_json(),
        lambda: pydantic_order.model_dump_json(),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 5: Large List JSON
    # ================================================================
    large_order = DhiOrder(
        id=999,
        customer="Large Customer",
        items=[{"name": f"Item {i}", "price": i * 1.5, "qty": i} for i in range(50)],
        total=12345.67,
    )
    large_pydantic_order = PydanticOrder(
        id=999,
        customer="Large Customer",
        items=[{"name": f"Item {i}", "price": i * 1.5, "qty": i} for i in range(50)],
        total=12345.67,
    )

    result = run_benchmark(
        "Large list JSON",
        lambda: large_order.model_dump_json(),
        lambda: large_pydantic_order.model_dump_json(),
        ITERATIONS // 5,
    )
    results.append(result)

    # ================================================================
    # Print Results
    # ================================================================
    print(f"Iterations: {ITERATIONS:,}")
    print()
    print("=" * 70)
    print(f"{'Benchmark':<25} {'dhi':>10} {'Pydantic':>12} {'Speedup':>10}")
    print("-" * 70)

    total_dhi = 0
    total_pydantic = 0

    for r in results:
        total_dhi += r.dhi_time_ms
        total_pydantic += r.pydantic_time_ms
        speedup_str = f"{r.speedup:.2f}x"
        print(f"{r.name:<25} {r.dhi_time_ms:>8.1f}ms {r.pydantic_time_ms:>10.1f}ms {speedup_str:>10}")

    print("-" * 70)
    overall_speedup = total_pydantic / total_dhi if total_dhi > 0 else 0
    print(f"{'TOTAL':<25} {total_dhi:>8.1f}ms {total_pydantic:>10.1f}ms {overall_speedup:>9.2f}x")
    print("=" * 70)
    print()

    if overall_speedup >= 1:
        print(f"dhi JSON is {overall_speedup:.2f}x FASTER than Pydantic!")
    else:
        print(f"dhi JSON is {1/overall_speedup:.2f}x slower than Pydantic")


if __name__ == "__main__":
    main()
