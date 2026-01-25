#!/bin/bash
# Run all TurboAPI benchmarks

set -e

echo "========================================"
echo "Running TurboAPI Benchmark Suite"
echo "========================================"
echo

cd "$(dirname "$0")/.."

echo "[1/4] Validation Benchmark"
python benchmarks/bench_validation.py
echo

echo "[2/4] JSON Benchmark"
python benchmarks/bench_json.py
echo

echo "[3/4] Memory Benchmark"
python benchmarks/bench_memory.py
echo

echo "[4/4] Throughput Benchmark"
python benchmarks/bench_throughput.py
echo

echo "========================================"
echo "All benchmarks complete!"
echo "========================================"
