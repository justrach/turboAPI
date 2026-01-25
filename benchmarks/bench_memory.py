#!/usr/bin/env python3
"""
Memory Usage Benchmark: TurboAPI vs FastAPI

Compares memory footprint and allocation patterns between frameworks.
"""

import gc
import sys
import tracemalloc
from dataclasses import dataclass
from typing import List

# Import validation libraries
import dhi
import pydantic


@dataclass
class MemoryResult:
    name: str
    dhi_peak_kb: float
    pydantic_peak_kb: float
    dhi_current_kb: float
    pydantic_current_kb: float
    ratio: float


def measure_memory(func, iterations: int = 10_000) -> tuple[float, float]:
    """Measure peak and current memory for a function."""
    gc.collect()
    tracemalloc.start()

    for _ in range(iterations):
        func()

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()

    return current / 1024, peak / 1024  # Convert to KB


def run_memory_benchmark(name: str, dhi_func, pydantic_func, iterations: int = 10_000) -> MemoryResult:
    """Run a memory benchmark comparing dhi vs pydantic."""
    gc.collect()

    dhi_current, dhi_peak = measure_memory(dhi_func, iterations)
    gc.collect()

    pydantic_current, pydantic_peak = measure_memory(pydantic_func, iterations)
    gc.collect()

    ratio = pydantic_peak / dhi_peak if dhi_peak > 0 else 0

    return MemoryResult(
        name=name,
        dhi_peak_kb=dhi_peak,
        pydantic_peak_kb=pydantic_peak,
        dhi_current_kb=dhi_current,
        pydantic_current_kb=pydantic_current,
        ratio=ratio,
    )


def main():
    print("=" * 70)
    print("Memory Usage Benchmark: dhi vs Pydantic")
    print("=" * 70)
    print()
    print(f"dhi version: {dhi.__version__} (native={dhi.HAS_NATIVE_EXT})")
    print(f"pydantic version: {pydantic.__version__}")
    print()

    results: List[MemoryResult] = []
    ITERATIONS = 10_000

    # ================================================================
    # Test 1: Simple Model Memory
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

    result = run_memory_benchmark(
        "Simple Model",
        lambda: DhiSimple(**simple_data),
        lambda: PydanticSimple(**simple_data),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 2: Nested Model Memory
    # ================================================================
    class DhiAddress(dhi.BaseModel):
        street: str
        city: str
        country: str

    class DhiPerson(dhi.BaseModel):
        name: str
        age: int
        addresses: list = []

    class PydanticAddress(pydantic.BaseModel):
        street: str
        city: str
        country: str

    class PydanticPerson(pydantic.BaseModel):
        name: str
        age: int
        addresses: list = []

    nested_data = {
        "name": "Bob",
        "age": 25,
        "addresses": [
            {"street": "123 Main St", "city": "NYC", "country": "USA"},
            {"street": "456 Oak Ave", "city": "LA", "country": "USA"},
        ],
    }

    result = run_memory_benchmark(
        "Nested Model",
        lambda: DhiPerson(**nested_data),
        lambda: PydanticPerson(**nested_data),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Test 3: Large List Field Memory
    # ================================================================
    large_list_data = {"name": "Test", "age": 30, "addresses": list(range(100))}

    result = run_memory_benchmark(
        "Large List Field",
        lambda: DhiPerson(**large_list_data),
        lambda: PydanticPerson(**large_list_data),
        ITERATIONS // 10,
    )
    results.append(result)

    # ================================================================
    # Test 4: JSON Serialization Memory
    # ================================================================
    dhi_instance = DhiSimple(**simple_data)
    pydantic_instance = PydanticSimple(**simple_data)

    result = run_memory_benchmark(
        "JSON Serialization",
        lambda: dhi_instance.model_dump_json(),
        lambda: pydantic_instance.model_dump_json(),
        ITERATIONS,
    )
    results.append(result)

    # ================================================================
    # Print Results
    # ================================================================
    print(f"Iterations: {ITERATIONS:,}")
    print()
    print("=" * 70)
    print(f"{'Benchmark':<20} {'dhi Peak':>12} {'Pydantic Peak':>14} {'Ratio':>10}")
    print("-" * 70)

    for r in results:
        ratio_str = f"{r.ratio:.2f}x" if r.ratio >= 1 else f"{r.ratio:.2f}x"
        print(f"{r.name:<20} {r.dhi_peak_kb:>10.1f}KB {r.pydantic_peak_kb:>12.1f}KB {ratio_str:>10}")

    print("=" * 70)
    print()

    avg_ratio = sum(r.ratio for r in results) / len(results) if results else 0
    if avg_ratio >= 1:
        print(f"dhi uses {avg_ratio:.2f}x LESS memory than Pydantic on average!")
    else:
        print(f"dhi uses {1/avg_ratio:.2f}x more memory than Pydantic on average")


if __name__ == "__main__":
    main()
