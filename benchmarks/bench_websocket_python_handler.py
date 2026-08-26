#!/usr/bin/env python3
"""Gate the existing persistent Python WebSocket handler path.

The benchmark keeps one connection open, verifies every echo response, and
reports the median of several trials for p50, p95, and messages/second. Pass a
baseline JSON produced by the same runner to enforce the 10% repository gate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import websockets

SERVER_CODE = r"""
import os

from turboapi import TurboAPI
from turboapi.websockets import WebSocket, WebSocketDisconnect

app = TurboAPI(title="websocket-python-handler-benchmark", version="0")

@app.get("/ping")
def ping():
    return {"ok": True}

@app.websocket("/ws")
async def echo(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            message = await ws.receive_text()
            await ws.send_text(message)
    except WebSocketDisconnect:
        pass

app.run(host="127.0.0.1", port=int(os.environ["TURBO_WS_BENCH_PORT"]))
"""


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _percentile(samples: list[float], percentile: float) -> float:
    return samples[max(0, int(len(samples) * percentile) - 1)]


async def _measure(port: int, *, iterations: int, warmup: int, trials: int) -> dict:
    payload = "turboapi-persistent-python-handler"
    results: list[dict[str, float | int]] = []
    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws",
        compression=None,
        max_queue=1,
        close_timeout=1,
    ) as websocket:
        for _ in range(warmup):
            await websocket.send(payload)
            response = await websocket.recv()
            if response != payload:
                raise AssertionError("Python handler returned the wrong payload")

        for _ in range(trials):
            samples: list[float] = []
            started = time.perf_counter_ns()
            for _ in range(iterations):
                one_started = time.perf_counter_ns()
                await websocket.send(payload)
                response = await websocket.recv()
                if response != payload:
                    raise AssertionError("Python handler returned the wrong payload")
                samples.append((time.perf_counter_ns() - one_started) / 1_000)
            elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
            samples.sort()
            results.append(
                {
                    "iterations": iterations,
                    "elapsed_s": elapsed,
                    "p50_us": statistics.median(samples),
                    "p95_us": _percentile(samples, 0.95),
                    "p99_us": _percentile(samples, 0.99),
                    "rps": iterations / elapsed,
                }
            )

    return {
        "path": "persistent_python_handler_echo",
        "trials": results,
        "median": {
            name: statistics.median(float(trial[name]) for trial in results)
            for name in ("p50_us", "p95_us", "p99_us", "rps")
        },
        "output_verified": True,
    }


def _compare(result: dict, baseline: dict, max_regression_pct: float) -> dict:
    current = result["median"]
    previous = baseline["median"]
    regressions = {
        "p50_us": (current["p50_us"] / previous["p50_us"] - 1) * 100,
        "p95_us": (current["p95_us"] / previous["p95_us"] - 1) * 100,
        "rps": (1 - current["rps"] / previous["rps"]) * 100,
    }
    result["comparison"] = {
        "baseline_median": previous,
        "regression_pct": regressions,
        "max_regression_pct": max_regression_pct,
        "passed": all(value <= max_regression_pct for value in regressions.values()),
    }
    return result


def _command_output(*args: str, cwd: pathlib.Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _provenance(source_root: pathlib.Path) -> dict[str, object]:
    extensions = sorted((source_root / "python" / "turboapi").glob("turbonet*.so"))
    extension = extensions[0] if len(extensions) == 1 else None
    zig = shutil.which("zig")
    return {
        "source_sha": _command_output("git", "rev-parse", "HEAD", cwd=source_root),
        "source_dirty": bool(
            _command_output(
                "git",
                "status",
                "--porcelain",
                "--untracked-files=no",
                cwd=source_root,
            )
        ),
        "extension_sha256": (
            hashlib.sha256(extension.read_bytes()).hexdigest() if extension else None
        ),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "zig": _command_output(zig, "version") if zig else None,
    }


def _wait_ready(port: int, process: subprocess.Popen, log_file) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=0.2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            if process.poll() is not None:
                break
            time.sleep(0.05)
    log_file.seek(0)
    output = log_file.read().decode("utf-8", errors="replace")
    raise RuntimeError(f"benchmark server failed to start (exit={process.poll()}):\n{output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--warmup", type=int, default=1_000)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--baseline", type=pathlib.Path)
    parser.add_argument("--max-regression-pct", type=float, default=10.0)
    args = parser.parse_args()
    if min(args.iterations, args.warmup, args.trials) < 1:
        parser.error("iterations, warmup, and trials must all be positive")

    source_root = args.source_root.resolve()
    package_root = source_root / "python"
    if not package_root.is_dir():
        parser.error(f"missing source package directory: {package_root}")

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(package_root), env["PYTHONPATH"]) if env.get("PYTHONPATH") else (str(package_root),)
    )
    env["PYTHON_GIL"] = "0"
    env["TURBO_DISABLE_RATE_LIMITING"] = "1"
    env["TURBO_DISABLE_CACHE"] = "1"
    # Keep base and head admission equivalent even though older bases reserve
    # HTTP workers while the new runtime has a dedicated WebSocket pool.
    env["TURBO_THREAD_POOL_SIZE"] = "24"
    env["TURBO_HTTP_WORKER_RESERVE"] = "4"
    env["TURBO_WS_WORKER_POOL_SIZE"] = "24"
    env["TURBO_MAX_WEBSOCKETS"] = "20"
    env["TURBO_WS_BENCH_PORT"] = str(port)

    with tempfile.TemporaryFile() as log_file:
        process = subprocess.Popen(
            [sys.executable, "-c", SERVER_CODE],
            cwd=source_root,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_ready(port, process, log_file)
            result = asyncio.run(
                _measure(
                    port,
                    iterations=args.iterations,
                    warmup=args.warmup,
                    trials=args.trials,
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    result["source_root"] = str(source_root)
    result["provenance"] = _provenance(source_root)
    if args.baseline:
        with args.baseline.open() as baseline_file:
            result = _compare(result, json.load(baseline_file), args.max_regression_pct)

    encoded = json.dumps(result, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n")
    return 0 if result.get("comparison", {}).get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
