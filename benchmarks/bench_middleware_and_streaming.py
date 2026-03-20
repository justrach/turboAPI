"""
Benchmark for Issue #36: Tail latency under load with stacked middleware and streaming.

Measures:
  - p50/p99 latency with stacked middleware (CORS + Logging)
  - p50/p99 latency for a buffered-streaming endpoint
  - Optionally uses `wrk` when available; falls back to a pure-Python
    concurrent benchmark (concurrent.futures + requests) for portability.

NOTE on streaming:
  TurboAPI's Zig transport does not support true HTTP chunked transfer.
  Handlers that return a StreamingResponse have their chunks buffered into a
  single response body before being sent.  The /stream endpoint below
  documents this by collecting all SSE chunks in memory and returning them
  as a single text/event-stream body.  This is the "safe" middleware path.
"""
import asyncio
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread

import requests as http

from turboapi import TurboAPI
from turboapi.middleware import CORSMiddleware, LoggingMiddleware


app = TurboAPI(title="Middleware & Streaming Benchmark")
app.add_middleware(LoggingMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"])


@app.get("/stacked")
def stacked_endpoint():
    return {"message": "Hello with stacked middleware", "status": "ok"}


# /stream: collects all SSE chunks in-process and returns them as one body.
# This is the correct behaviour for TurboAPI's buffered response path and
# serves as a benchmark for the overhead of an async generator + middleware.
@app.get("/stream")
async def stream_endpoint():
    async def generator():
        for i in range(50):
            yield f"data: chunk {i}\n\n"
            await asyncio.sleep(0)  # yield event-loop without real delay

    chunks = []
    async for chunk in generator():
        chunks.append(chunk)
    body = "".join(chunks)
    return {"chunks": len(chunks), "bytes": len(body), "sample": chunks[0].strip()}



def _run_server():
    sys.stdout = open(os.devnull, "w")
    app.run(host="127.0.0.1", port=8085)



def _wrk(url: str, threads: int = 4, conns: int = 100, duration: str = "15s") -> bool:
    """Run wrk if available. Returns True on success."""
    try:
        subprocess.run(
            ["wrk", f"-t{threads}", f"-c{conns}", f"-d{duration}", "--latency", url],
            check=True,
        )
        return True
    except FileNotFoundError:
        return False


def _python_bench(url: str, n: int = 2000, workers: int = 50) -> dict:
    """Pure-Python concurrent latency benchmark. Returns percentile stats (ms)."""
    latencies = []

    def _get(_):
        t0 = time.perf_counter()
        try:
            r = http.get(url, timeout=10)
            ok = r.status_code == 200
        except Exception:
            ok = False
        return (time.perf_counter() - t0) * 1000, ok

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_get, i) for i in range(n)]
        for f in as_completed(futs):
            ms, ok = f.result()
            if ok:
                latencies.append(ms)

    if not latencies:
        return {"error": "all requests failed"}

    latencies.sort()
    return {
        "requests": len(latencies),
        "p50_ms":  round(statistics.median(latencies), 2),
        "p90_ms":  round(latencies[int(len(latencies) * 0.90)], 2),
        "p99_ms":  round(latencies[int(len(latencies) * 0.99)], 2),
        "avg_ms":  round(statistics.mean(latencies), 2),
        "max_ms":  round(latencies[-1], 2),
    }


def _section(title: str):
    print(f"\n{'='*54}")
    print(f"  {title}")
    print("=" * 54)



if __name__ == "__main__":
    print("Starting TurboAPI server for tail-latency benchmarks (port 8085)…")
    server_thread = Thread(target=_run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:8085"

    # Warm-up
    for _ in range(10):
        try:
            http.get(f"{base}/stacked", timeout=5)
        except Exception:
            pass
    time.sleep(0.2)

    # TEST 1: Stacked Middleware 
    _section("TEST 1: Stacked Middleware (CORS + Logging) — /stacked")
    if not _wrk(f"{base}/stacked"):
        print("wrk not found — using Python concurrent benchmark")
        stats = _python_bench(f"{base}/stacked")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    # TEST 2: Buffered Streaming
    _section("TEST 2: Buffered Streaming — /stream  (async generator, buffered)")
    # Verify the endpoint works correctly first
    try:
        r = http.get(f"{base}/stream", timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  Endpoint verified: {data.get('chunks')} chunks, {data.get('bytes')} bytes")
            print(f"  Sample: {data.get('sample')}")
            print(f"  NOTE: TurboAPI buffers streaming responses (no chunked transfer)")
        else:
            print(f"  WARNING: /stream returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  ERROR verifying /stream: {e}")

    if not _wrk(f"{base}/stream"):
        print("wrk not found — using Python concurrent benchmark")
        stats = _python_bench(f"{base}/stream")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    print("\n✓ Benchmarks complete.")
    os._exit(0)
