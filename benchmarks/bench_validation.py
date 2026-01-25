#!/usr/bin/env python3
"""
Validation Layer Benchmark: dhi vs Pydantic

Compares the core validation performance between TurboAPI (dhi) and FastAPI (Pydantic).
This is the foundational performance difference between the frameworks.
"""

import time
import sys
import json
from dataclasses import dataclass
from typing import Optional

# Import validation libraries
import dhi
import pydantic


@dataclass
class BenchmarkResult:
    name: str
    dhi_time_ms: float
    pydantic_time_ms: float
    speedup: float
    iterations: int


def run_benchmark(name: str, dhi_func, pydantic_func, iterations: int = 100_000) -> BenchmarkResult:
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

    return BenchmarkResult(
        name=name,
        dhi_time_ms=dhi_time,
        pydantic_time_ms=pydantic_time,
        speedup=speedup,
        iterations=iterations,
    )


def main():
    print("=" * 70)
    print("Validation Layer Benchmark: dhi vs Pydantic")
    print("=" * 70)
    print()
    print(f"dhi version: {dhi.__version__} (native={dhi.HAS_NATIVE_EXT})")
    print(f"pydantic version: {pydantic.__version__}")
    print()

    results = []
    ITERATIONS = 100_000

    # ================================================================
    # Test 1: Simple Model Creation
    # ================================================================
    class DhiSimple(dhi.BaseModel):
        name: str
        age: int
        active: bool = True

    class PydanticSimple(pydantic.BaseModel):
        name: str
        age: int
        active: bool = True

    simple_data = {"name": "Alice", "age": 30, "active": True}

    result = run_benchmark(
        "Simple Model Creation",
        lambda: DhiSimple(**simple_data),
        lambda: PydanticSimple(**simple_data),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 2: Model Validation (model_validate)
    # ================================================================
    result = run_benchmark(
        "Model Validation",
        lambda: DhiSimple.model_validate(simple_data),
        lambda: PydanticSimple.model_validate(simple_data),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 3: Model Dump (model_dump)
    # ================================================================
    dhi_instance = DhiSimple(**simple_data)
    pydantic_instance = PydanticSimple(**simple_data)

    result = run_benchmark(
        "Model Dump",
        lambda: dhi_instance.model_dump(),
        lambda: pydantic_instance.model_dump(),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 4: JSON Serialization (model_dump_json)
    # ================================================================
    result = run_benchmark(
        "JSON Serialization",
        lambda: dhi_instance.model_dump_json(),
        lambda: pydantic_instance.model_dump_json(),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 5: Complex Nested Model
    # ================================================================
    class DhiAddress(dhi.BaseModel):
        street: str
        city: str
        country: str

    class DhiUser(dhi.BaseModel):
        id: int
        name: str
        email: str
        tags: list = []

    class PydanticAddress(pydantic.BaseModel):
        street: str
        city: str
        country: str

    class PydanticUser(pydantic.BaseModel):
        id: int
        name: str
        email: str
        tags: list = []

    complex_data = {
        "id": 1,
        "name": "Alice Smith",
        "email": "alice@example.com",
        "tags": ["admin", "user", "premium"],
    }

    result = run_benchmark(
        "Complex Model Creation",
        lambda: DhiUser(**complex_data),
        lambda: PydanticUser(**complex_data),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 6: Large List Validation
    # ================================================================
    large_list_data = {"id": 1, "name": "Test", "email": "test@example.com", "tags": list(range(100))}

    result = run_benchmark(
        "Large List Field",
        lambda: DhiUser(**large_list_data),
        lambda: PydanticUser(**large_list_data),
        ITERATIONS // 10,  # Fewer iterations for larger data
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
        speedup_str = f"{r.speedup:.2f}x" if r.speedup >= 1 else f"{r.speedup:.2f}x"
        print(f"{r.name:<25} {r.dhi_time_ms:>8.1f}ms {r.pydantic_time_ms:>10.1f}ms {speedup_str:>10}")

    print("-" * 70)
    overall_speedup = total_pydantic / total_dhi if total_dhi > 0 else 0
    print(f"{'TOTAL':<25} {total_dhi:>8.1f}ms {total_pydantic:>10.1f}ms {overall_speedup:>9.2f}x")
    print("=" * 70)
    print()

    # Summary
    if overall_speedup >= 1:
        print(f"✓ dhi is {overall_speedup:.2f}x FASTER than Pydantic overall!")
    else:
        print(f"✗ dhi is {1/overall_speedup:.2f}x slower than Pydantic overall")

    # Save results as JSON
    results_json = {
        "dhi_version": dhi.__version__,
        "pydantic_version": pydantic.__version__,
        "dhi_native_ext": dhi.HAS_NATIVE_EXT,
        "iterations": ITERATIONS,
        "benchmarks": [
            {
                "name": r.name,
                "dhi_ms": r.dhi_time_ms,
                "pydantic_ms": r.pydantic_time_ms,
                "speedup": r.speedup,
            }
            for r in results
        ],
        "summary": {
            "total_dhi_ms": total_dhi,
            "total_pydantic_ms": total_pydantic,
            "overall_speedup": overall_speedup,
        },
    }

    with open("benchmarks/results_validation.json", "w") as f:
        json.dump(results_json, f, indent=2)
    print(f"\nResults saved to benchmarks/results_validation.json")


if __name__ == "__main__":
    main()
