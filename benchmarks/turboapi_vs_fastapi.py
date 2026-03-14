#!/usr/bin/env python3
"""
TurboAPI vs FastAPI — real HTTP benchmark using wrk.

Starts each server, hammers it with wrk, parses the output, and prints a
side-by-side comparison table.

Usage:
    python benchmarks/turboapi_vs_fastapi.py            # default 10s per test
    python benchmarks/turboapi_vs_fastapi.py --duration 5 --threads 4 --connections 50
"""

import argparse
import re
import socket
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass

# ── helpers ──────────────────────────────────────────────────────────────────


def wait_for_server(port: int, timeout: float = 10.0):
    """Block until a TCP connection to localhost:port succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_wrk(
    port: int,
    path: str,
    *,
    duration: int,
    threads: int,
    connections: int,
    script: str | None = None,
) -> dict:
    """Run wrk and return parsed results."""
    cmd = [
        "wrk",
        f"-t{threads}",
        f"-c{connections}",
        f"-d{duration}s",
        "--latency",
    ]
    if script:
        cmd += ["-s", script]
    cmd.append(f"http://127.0.0.1:{port}{path}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
    output = result.stdout + result.stderr
    return parse_wrk_output(output)


def parse_wrk_output(output: str) -> dict:
    """Extract key metrics from wrk stdout."""
    data: dict = {"raw": output}

    # Requests/sec:  12345.67
    m = re.search(r"Requests/sec:\s+([\d.]+)", output)
    data["rps"] = float(m.group(1)) if m else 0.0

    # Latency   avg    stdev   max   +/- Stdev
    #           1.23ms  0.45ms 12.34ms  78.90%
    m = re.search(r"Latency\s+([\d.]+\w+)\s+([\d.]+\w+)\s+([\d.]+\w+)", output)
    if m:
        data["lat_avg"] = m.group(1)
        data["lat_stdev"] = m.group(2)
        data["lat_max"] = m.group(3)
    else:
        data["lat_avg"] = data["lat_stdev"] = data["lat_max"] = "N/A"

    # Transfer/sec
    m = re.search(r"Transfer/sec:\s+([\d.]+\w+)", output)
    data["transfer"] = m.group(1) if m else "N/A"

    # Socket errors
    m = re.search(
        r"Socket errors:.*?(\d+)\s+connect.*?(\d+)\s+read.*?(\d+)\s+write.*?(\d+)\s+timeout", output
    )
    if m:
        data["errors"] = sum(int(m.group(i)) for i in range(1, 5))
    else:
        data["errors"] = 0

    # Total requests
    m = re.search(r"(\d+)\s+requests\s+in", output)
    data["total_requests"] = int(m.group(1)) if m else 0

    return data


# ── server launchers ─────────────────────────────────────────────────────────


def run_fastapi_server(port: int):
    """Run FastAPI + Uvicorn in a subprocess."""
    code = textwrap.dedent(f"""\
        import uvicorn
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Item(BaseModel):
            name: str
            price: float
            quantity: int = 1

        @app.get("/")
        def root():
            return {{"message": "Hello World"}}

        @app.get("/items/{{item_id}}")
        def get_item(item_id: int):
            return {{"item_id": item_id, "name": "Test Item", "price": 9.99}}

        @app.post("/items")
        def create_item(item: Item):
            return {{"item": item.model_dump(), "created": True}}

        @app.get("/users/{{user_id}}/posts/{{post_id}}")
        def get_user_post(user_id: int, post_id: int):
            return {{"user_id": user_id, "post_id": post_id, "title": "Hello"}}

        if __name__ == "__main__":
            uvicorn.run(app, host="127.0.0.1", port={port},
                        log_level="warning", access_log=False)
    """)
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_turboapi_server(port: int):
    """Run TurboAPI + Zig backend in a subprocess."""
    code = textwrap.dedent(f"""\
        import os, sys
        os.environ["TURBO_DISABLE_RATE_LIMITING"] = "1"

        from turboapi import TurboAPI

        try:
            from dhi import BaseModel
        except ImportError:
            from pydantic import BaseModel

        app = TurboAPI(title="Bench", version="1.0")

        class Item(BaseModel):
            name: str
            price: float
            quantity: int = 1

        @app.get("/")
        def root():
            return {{"message": "Hello World"}}

        @app.get("/items/{{item_id}}")
        def get_item(item_id: int):
            return {{"item_id": item_id, "name": "Test Item", "price": 9.99}}

        @app.post("/items")
        def create_item(item: Item):
            return {{"item": item.model_dump(), "created": True}}

        @app.get("/users/{{user_id}}/posts/{{post_id}}")
        def get_user_post(user_id: int, post_id: int):
            return {{"user_id": user_id, "post_id": post_id, "title": "Hello"}}

        app.run(host="127.0.0.1", port={port})
    """)
    # Use temp file for stderr so we can read errors without pipe deadlock
    # (the server runs forever, so PIPE would fill and block)
    import tempfile

    err_file = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=err_file,
    )
    proc._turbo_err_path = err_file.name  # stash path for error reporting
    return proc


# ── wrk lua script for POST ─────────────────────────────────────────────────

WRK_POST_LUA = """\
wrk.method = "POST"
wrk.body   = '{"name": "Widget", "price": 9.99, "quantity": 5}'
wrk.headers["Content-Type"] = "application/json"
"""


# ── benchmark runner ─────────────────────────────────────────────────────────


@dataclass
class TestCase:
    name: str
    path: str
    script: str | None = None


@dataclass
class Result:
    test: str
    turbo_rps: float
    fastapi_rps: float
    turbo_lat: str
    fastapi_lat: str
    turbo_errors: int
    fastapi_errors: int

    @property
    def speedup(self) -> float:
        return self.turbo_rps / self.fastapi_rps if self.fastapi_rps > 0 else 0.0


def main():
    parser = argparse.ArgumentParser(description="TurboAPI vs FastAPI benchmark")
    parser.add_argument(
        "-d", "--duration", type=int, default=10, help="Seconds per test (default: 10)"
    )
    parser.add_argument("-t", "--threads", type=int, default=4, help="wrk threads (default: 4)")
    parser.add_argument(
        "-c", "--connections", type=int, default=100, help="wrk connections (default: 100)"
    )
    args = parser.parse_args()

    # Check wrk is available
    if not subprocess.run(["which", "wrk"], capture_output=True).returncode == 0:
        print("ERROR: wrk not found. Install with: brew install wrk")
        sys.exit(1)

    turbo_port = 9100
    fastapi_port = 9200

    # Kill any leftover processes on these ports
    for port in (turbo_port, fastapi_port):
        subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True,
        )
    time.sleep(0.5)

    # Write POST lua script
    lua_path = "/tmp/turbo_bench_post.lua"
    with open(lua_path, "w") as f:
        f.write(WRK_POST_LUA)

    tests = [
        TestCase("GET /", "/"),
        TestCase("GET /items/{id}", "/items/42"),
        TestCase("GET /users/{id}/posts/{id}", "/users/7/posts/99"),
        TestCase("POST /items (JSON)", "/items", lua_path),
    ]

    print()
    print("=" * 78)
    print("  TurboAPI (Zig backend) vs FastAPI (Uvicorn) — HTTP Benchmark")
    print("=" * 78)
    print(
        f"  wrk: {args.threads} threads, {args.connections} connections, {args.duration}s per test"
    )
    print(f"  Python: {sys.version.split()[0]}")
    print()

    # ── Start servers ────────────────────────────────────────────────────────
    print("  Starting FastAPI (Uvicorn)...", end=" ", flush=True)
    fastapi_proc = run_fastapi_server(fastapi_port)
    if not wait_for_server(fastapi_port):
        print("FAILED (timeout)")
        fastapi_proc.kill()
        sys.exit(1)
    print(f"✅  port {fastapi_port}")

    print("  Starting TurboAPI (Zig)...", end=" ", flush=True)
    turbo_proc = run_turboapi_server(turbo_port)
    if not wait_for_server(turbo_port, timeout=15.0):
        print("FAILED (timeout)")
        turbo_proc.kill()
        turbo_proc.wait()
        # Read stderr from temp file
        err_path = getattr(turbo_proc, "_turbo_err_path", None)
        if err_path:
            try:
                with open(err_path) as f:
                    err_text = f.read().strip()
                if err_text:
                    print("  Server stderr:")
                    for line in err_text.splitlines()[-20:]:
                        print(f"    {line}")
            except Exception:
                pass
        fastapi_proc.kill()
        sys.exit(1)
    print(f"✅  port {turbo_port}")
    print()

    # ── Warmup ───────────────────────────────────────────────────────────────
    print("  Warming up (2s each)...", flush=True)
    for t in tests:
        run_wrk(turbo_port, t.path, duration=2, threads=2, connections=10, script=t.script)
        run_wrk(fastapi_port, t.path, duration=2, threads=2, connections=10, script=t.script)
    print()

    # ── Run benchmarks ───────────────────────────────────────────────────────
    results: list[Result] = []

    for t in tests:
        print(f"  ▸ {t.name}", flush=True)

        # TurboAPI
        print("    TurboAPI ...", end=" ", flush=True)
        turbo = run_wrk(
            turbo_port,
            t.path,
            duration=args.duration,
            threads=args.threads,
            connections=args.connections,
            script=t.script,
        )
        print(f"{turbo['rps']:,.0f} req/s")

        # FastAPI
        print("    FastAPI  ...", end=" ", flush=True)
        fast = run_wrk(
            fastapi_port,
            t.path,
            duration=args.duration,
            threads=args.threads,
            connections=args.connections,
            script=t.script,
        )
        print(f"{fast['rps']:,.0f} req/s")

        results.append(
            Result(
                test=t.name,
                turbo_rps=turbo["rps"],
                fastapi_rps=fast["rps"],
                turbo_lat=turbo["lat_avg"],
                fastapi_lat=fast["lat_avg"],
                turbo_errors=turbo["errors"],
                fastapi_errors=fast["errors"],
            )
        )
        print()

    # ── Stop servers ─────────────────────────────────────────────────────────
    turbo_proc.kill()
    fastapi_proc.kill()
    turbo_proc.wait()
    fastapi_proc.wait()

    # ── Results table ────────────────────────────────────────────────────────
    print("=" * 78)
    print(
        f"  {'Endpoint':<28} {'TurboAPI':>12} {'FastAPI':>12} {'Speedup':>10} {'Latency (T/F)':>16}"
    )
    print("-" * 78)

    for r in results:
        arrow = "🟢" if r.speedup >= 1.0 else "🔴"
        print(
            f"  {r.test:<28} {r.turbo_rps:>10,.0f}/s {r.fastapi_rps:>10,.0f}/s "
            f"{arrow} {r.speedup:>6.2f}x  {r.turbo_lat:>6}/{r.fastapi_lat:<6}"
        )

    print("=" * 78)

    avg = sum(r.speedup for r in results) / len(results) if results else 0
    turbo_total = sum(r.turbo_rps for r in results)
    fast_total = sum(r.fastapi_rps for r in results)
    total_errors = sum(r.turbo_errors + r.fastapi_errors for r in results)

    print()
    print(f"  Average speedup:  {avg:.2f}x")
    print(f"  Total req/s:      TurboAPI {turbo_total:,.0f}  vs  FastAPI {fast_total:,.0f}")
    if total_errors > 0:
        print(f"  ⚠️  Socket errors detected: {total_errors}")
    print()


if __name__ == "__main__":
    main()
