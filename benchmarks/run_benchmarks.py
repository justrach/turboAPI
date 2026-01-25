#!/usr/bin/env python3
"""
TurboAPI vs FastAPI Benchmark Suite

Comprehensive benchmarks comparing TurboAPI and FastAPI across multiple scenarios.
Uses wrk for HTTP load testing.

Requirements:
- wrk: brew install wrk (macOS) or apt install wrk (Ubuntu)
- fastapi: pip install fastapi uvicorn
- turboapi: pip install -e ./python

Usage:
    PYTHON_GIL=0 python benchmarks/run_benchmarks.py
"""

import subprocess
import time
import signal
import os
import sys
import json
from dataclasses import dataclass
from typing import Optional

# Benchmark configuration
BENCHMARK_DURATION = 10  # seconds
BENCHMARK_THREADS = 4
BENCHMARK_CONNECTIONS = 100
WARMUP_REQUESTS = 1000


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    framework: str
    endpoint: str
    requests_per_second: float
    latency_avg_ms: float
    latency_p99_ms: float
    transfer_per_sec: str
    errors: int


def parse_wrk_output(output: str) -> dict:
    """Parse wrk output to extract metrics."""
    lines = output.strip().split('\n')
    result = {
        'requests_per_second': 0,
        'latency_avg_ms': 0,
        'latency_p99_ms': 0,
        'transfer_per_sec': '0',
        'errors': 0
    }

    for line in lines:
        line = line.strip()
        # Parse requests/sec
        if 'Requests/sec:' in line:
            try:
                result['requests_per_second'] = float(line.split(':')[1].strip())
            except (IndexError, ValueError):
                pass
        # Parse latency average
        elif line.startswith('Latency') and 'Stdev' not in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    latency = parts[1]
                    if 'ms' in latency:
                        result['latency_avg_ms'] = float(latency.replace('ms', ''))
                    elif 'us' in latency:
                        result['latency_avg_ms'] = float(latency.replace('us', '')) / 1000
                    elif 's' in latency:
                        result['latency_avg_ms'] = float(latency.replace('s', '')) * 1000
                except ValueError:
                    pass
        # Parse 99th percentile
        elif '99%' in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    latency = parts[1]
                    if 'ms' in latency:
                        result['latency_p99_ms'] = float(latency.replace('ms', ''))
                    elif 'us' in latency:
                        result['latency_p99_ms'] = float(latency.replace('us', '')) / 1000
                    elif 's' in latency:
                        result['latency_p99_ms'] = float(latency.replace('s', '')) * 1000
                except ValueError:
                    pass
        # Parse transfer rate
        elif 'Transfer/sec:' in line:
            try:
                result['transfer_per_sec'] = line.split(':')[1].strip()
            except IndexError:
                pass
        # Parse errors
        elif 'Socket errors:' in line or 'Non-2xx' in line:
            result['errors'] += 1

    return result


def run_wrk(url: str, duration: int = 10, threads: int = 4, connections: int = 100,
            method: str = "GET", body: str = None) -> dict:
    """Run wrk benchmark and return results."""
    cmd = [
        'wrk',
        '-t', str(threads),
        '-c', str(connections),
        '-d', f'{duration}s',
        '--latency',
        url
    ]

    if method == "POST" and body:
        script = f'''
wrk.method = "POST"
wrk.body   = '{body}'
wrk.headers["Content-Type"] = "application/json"
'''
        script_file = '/tmp/wrk_post.lua'
        with open(script_file, 'w') as f:
            f.write(script)
        cmd.extend(['-s', script_file])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        return parse_wrk_output(result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return {'requests_per_second': 0, 'latency_avg_ms': 0, 'latency_p99_ms': 0, 'transfer_per_sec': '0', 'errors': 1}
    except FileNotFoundError:
        print("ERROR: wrk not found. Install with: brew install wrk")
        sys.exit(1)


def start_server(cmd: list, port: int, env: dict = None) -> subprocess.Popen:
    """Start a server process and wait for it to be ready."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=full_env
    )

    # Wait for server to start
    import urllib.request
    import urllib.error

    for _ in range(50):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
            return proc
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.2)

    proc.kill()
    raise RuntimeError(f"Server failed to start on port {port}")


def stop_server(proc: subprocess.Popen):
    """Stop a server process."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ============================================================================
# Benchmark Servers
# ============================================================================

TURBOAPI_SERVER = '''
from turboapi import TurboAPI, JSONResponse
from dhi import BaseModel
from typing import Optional

app = TurboAPI()

class Item(BaseModel):
    name: str
    price: float
    description: Optional[str] = None

@app.get("/")
def root():
    return {"message": "Hello, World!"}

@app.get("/json")
def json_response():
    return {"data": [1, 2, 3, 4, 5], "status": "ok", "count": 5}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.post("/items")
def create_item(item: Item):
    return {"created": True, "item": item.model_dump()}

@app.get("/status201")
def status_201():
    return JSONResponse(content={"created": True}, status_code=201)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001)
'''

FASTAPI_SERVER = '''
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    description: Optional[str] = None

@app.get("/")
def root():
    return {"message": "Hello, World!"}

@app.get("/json")
def json_response():
    return {"data": [1, 2, 3, 4, 5], "status": "ok", "count": 5}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.post("/items")
def create_item(item: Item):
    return {"created": True, "item": item.model_dump()}

@app.get("/status201")
def status_201():
    return JSONResponse(content={"created": True}, status_code=201)
'''


def run_benchmarks():
    """Run all benchmarks and print results."""
    print("=" * 70)
    print("TurboAPI vs FastAPI Benchmark Suite")
    print("=" * 70)
    print(f"Duration: {BENCHMARK_DURATION}s | Threads: {BENCHMARK_THREADS} | Connections: {BENCHMARK_CONNECTIONS}")
    print("=" * 70)

    results = []

    # Write server files
    with open('/tmp/turboapi_bench.py', 'w') as f:
        f.write(TURBOAPI_SERVER)

    with open('/tmp/fastapi_bench.py', 'w') as f:
        f.write(FASTAPI_SERVER)

    benchmarks = [
        ("GET /", "/", "GET", None),
        ("GET /json", "/json", "GET", None),
        ("GET /users/123", "/users/123", "GET", None),
        ("POST /items", "/items", "POST", '{"name":"Widget","price":9.99}'),
        ("GET /status201", "/status201", "GET", None),
    ]

    # Run TurboAPI benchmarks
    print("\n--- TurboAPI (Rust + Python 3.13 Free-Threading) ---")
    try:
        turbo_proc = start_server(
            ['python', '/tmp/turboapi_bench.py'],
            8001,
            {'PYTHON_GIL': '0', 'TURBO_DISABLE_RATE_LIMITING': '1'}
        )
        time.sleep(2)  # Extra warmup

        for name, path, method, body in benchmarks:
            url = f'http://127.0.0.1:8001{path}'
            print(f"  Benchmarking: {name}...", end=" ", flush=True)
            result = run_wrk(url, BENCHMARK_DURATION, BENCHMARK_THREADS, BENCHMARK_CONNECTIONS, method, body)
            print(f"{result['requests_per_second']:,.0f} req/s")
            results.append(BenchmarkResult(
                framework="TurboAPI",
                endpoint=name,
                requests_per_second=result['requests_per_second'],
                latency_avg_ms=result['latency_avg_ms'],
                latency_p99_ms=result['latency_p99_ms'],
                transfer_per_sec=result['transfer_per_sec'],
                errors=result['errors']
            ))

        stop_server(turbo_proc)
    except Exception as e:
        print(f"  Error: {e}")

    time.sleep(2)

    # Run FastAPI benchmarks
    print("\n--- FastAPI (uvicorn) ---")
    try:
        fastapi_proc = start_server(
            ['uvicorn', 'fastapi_bench:app', '--host', '127.0.0.1', '--port', '8002',
             '--workers', '1', '--log-level', 'error'],
            8002,
            {'PYTHONPATH': '/tmp'}
        )
        time.sleep(2)  # Extra warmup

        for name, path, method, body in benchmarks:
            url = f'http://127.0.0.1:8002{path}'
            print(f"  Benchmarking: {name}...", end=" ", flush=True)
            result = run_wrk(url, BENCHMARK_DURATION, BENCHMARK_THREADS, BENCHMARK_CONNECTIONS, method, body)
            print(f"{result['requests_per_second']:,.0f} req/s")
            results.append(BenchmarkResult(
                framework="FastAPI",
                endpoint=name,
                requests_per_second=result['requests_per_second'],
                latency_avg_ms=result['latency_avg_ms'],
                latency_p99_ms=result['latency_p99_ms'],
                transfer_per_sec=result['transfer_per_sec'],
                errors=result['errors']
            ))

        stop_server(fastapi_proc)
    except Exception as e:
        print(f"  Error: {e}")

    # Print comparison table
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS COMPARISON")
    print("=" * 70)
    print(f"{'Endpoint':<20} {'TurboAPI':>12} {'FastAPI':>12} {'Speedup':>10}")
    print("-" * 70)

    turbo_results = {r.endpoint: r for r in results if r.framework == "TurboAPI"}
    fastapi_results = {r.endpoint: r for r in results if r.framework == "FastAPI"}

    speedups = []
    for name, _, _, _ in benchmarks:
        turbo = turbo_results.get(name)
        fastapi = fastapi_results.get(name)
        if turbo and fastapi and fastapi.requests_per_second > 0:
            speedup = turbo.requests_per_second / fastapi.requests_per_second
            speedups.append(speedup)
            print(f"{name:<20} {turbo.requests_per_second:>10,.0f}/s {fastapi.requests_per_second:>10,.0f}/s {speedup:>9.1f}x")
        elif turbo:
            print(f"{name:<20} {turbo.requests_per_second:>10,.0f}/s {'N/A':>12} {'N/A':>10}")

    if speedups:
        avg_speedup = sum(speedups) / len(speedups)
        print("-" * 70)
        print(f"{'AVERAGE SPEEDUP':<20} {'':<12} {'':<12} {avg_speedup:>9.1f}x")

    print("\n" + "=" * 70)
    print("LATENCY COMPARISON (avg / p99)")
    print("=" * 70)
    print(f"{'Endpoint':<20} {'TurboAPI':>18} {'FastAPI':>18}")
    print("-" * 70)

    for name, _, _, _ in benchmarks:
        turbo = turbo_results.get(name)
        fastapi = fastapi_results.get(name)
        if turbo and fastapi:
            turbo_lat = f"{turbo.latency_avg_ms:.2f}ms / {turbo.latency_p99_ms:.2f}ms"
            fastapi_lat = f"{fastapi.latency_avg_ms:.2f}ms / {fastapi.latency_p99_ms:.2f}ms"
            print(f"{name:<20} {turbo_lat:>18} {fastapi_lat:>18}")

    print("=" * 70)

    # Return results for README generation
    return results, avg_speedup if speedups else 0


if __name__ == "__main__":
    run_benchmarks()
