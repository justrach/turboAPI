#!/usr/bin/env python3
"""Order-reversed c256+c32 HTTP gate for short embedding requests."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import pathlib
import statistics
import time
from typing import Any


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, math.ceil((percentile_value / 100.0) * len(ordered)) - 1)
    return ordered[index]


def summarize_lane(
    *,
    elapsed: float,
    foreground_latencies_ms: list[float],
    background_latencies_ms: list[float],
    error_count: int,
    error_samples: list[str],
) -> dict[str, Any]:
    foreground_requests = len(foreground_latencies_ms)
    background_requests = len(background_latencies_ms)
    return {
        "elapsed_seconds": elapsed,
        "combined_rps": (foreground_requests + background_requests) / elapsed,
        "errors": error_count,
        "error_samples": error_samples,
        "foreground": {
            "requests": foreground_requests,
            "rps": foreground_requests / elapsed,
            "p50_ms": percentile(foreground_latencies_ms, 50),
            "p95_ms": percentile(foreground_latencies_ms, 95),
            "p99_ms": percentile(foreground_latencies_ms, 99),
            "max_ms": max(foreground_latencies_ms, default=math.nan),
        },
        "background": {
            "requests": background_requests,
            "rps": background_requests / elapsed,
            "p50_ms": percentile(background_latencies_ms, 50),
            "p95_ms": percentile(background_latencies_ms, 95),
            "p99_ms": percentile(background_latencies_ms, 99),
            "max_ms": max(background_latencies_ms, default=math.nan),
        },
    }


def compare_runs(
    control_runs: list[dict[str, Any]],
    candidate_runs: list[dict[str, Any]],
    *,
    max_regression_percent: float,
) -> dict[str, Any]:
    """Compare medians and apply the same throughput/p95/p99 gate as issue #219."""
    if not control_runs or len(control_runs) != len(candidate_runs):
        raise ValueError("control and candidate require the same non-zero number of runs")

    def median(runs: list[dict[str, Any]], *keys: str) -> float:
        values: list[float] = []
        for run in runs:
            value: Any = run
            for key in keys:
                value = value[key]
            values.append(float(value))
        return statistics.median(values)

    control = {
        "combined_rps": median(control_runs, "combined_rps"),
        "foreground_p95_ms": median(control_runs, "foreground", "p95_ms"),
        "foreground_p99_ms": median(control_runs, "foreground", "p99_ms"),
        "errors": sum(int(run["errors"]) for run in control_runs),
    }
    candidate = {
        "combined_rps": median(candidate_runs, "combined_rps"),
        "foreground_p95_ms": median(candidate_runs, "foreground", "p95_ms"),
        "foreground_p99_ms": median(candidate_runs, "foreground", "p99_ms"),
        "errors": sum(int(run["errors"]) for run in candidate_runs),
    }
    deltas = {
        "combined_rps_percent": (candidate["combined_rps"] / control["combined_rps"] - 1) * 100,
        "foreground_p95_percent": (
            candidate["foreground_p95_ms"] / control["foreground_p95_ms"] - 1
        )
        * 100,
        "foreground_p99_percent": (
            candidate["foreground_p99_ms"] / control["foreground_p99_ms"] - 1
        )
        * 100,
    }
    failures = []
    if control["errors"] or candidate["errors"]:
        failures.append("HTTP or response-shape errors were observed")
    if deltas["combined_rps_percent"] < -max_regression_percent:
        failures.append("combined throughput regressed beyond the allowed threshold")
    if deltas["foreground_p95_percent"] > max_regression_percent:
        failures.append("foreground p95 regressed beyond the allowed threshold")
    if deltas["foreground_p99_percent"] > max_regression_percent:
        failures.append("foreground p99 regressed beyond the allowed threshold")
    return {
        "control_median": control,
        "candidate_median": candidate,
        "candidate_minus_control_percent": deltas,
        "max_regression_percent": max_regression_percent,
        "passed": not failures,
        "failures": failures,
    }


def _validate_embedding_response(body: Any, expected_rows: int, dimensions: int) -> None:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("response has no data list")
    if len(body["data"]) != expected_rows:
        raise ValueError(f"expected {expected_rows} rows, received {len(body['data'])}")
    for row in body["data"]:
        vector = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ValueError(f"expected a {dimensions}D embedding vector")


async def run_lane(
    *,
    base_url: str,
    foreground_path: str,
    background_path: str,
    foreground_concurrency: int,
    background_concurrency: int,
    duration_seconds: float,
    payload: dict[str, Any],
    dimensions: int,
) -> dict[str, Any]:
    try:
        import aiohttp
    except ImportError as exc:
        raise SystemExit("aiohttp is required; install `turboapi[benchmark]`") from exc

    inputs = payload.get("input")
    expected_rows = len(inputs) if isinstance(inputs, list) else 1
    foreground_latencies: list[float] = []
    background_latencies: list[float] = []
    error_count = 0
    error_samples: list[str] = []
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration_seconds

    timeout = aiohttp.ClientTimeout(total=max(10.0, duration_seconds))
    connector = aiohttp.TCPConnector(
        limit=foreground_concurrency + background_concurrency,
        force_close=False,
    )

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:

        async def worker(path: str, latencies: list[float]) -> None:
            nonlocal error_count
            await started.wait()
            while loop.time() < deadline:
                request_started = time.perf_counter()
                try:
                    async with session.post(f"{base_url.rstrip('/')}{path}", json=payload) as response:
                        if response.status != 200:
                            raise ValueError(f"HTTP {response.status}: {(await response.text())[:160]}")
                        body = await response.json(content_type=None)
                    _validate_embedding_response(body, expected_rows, dimensions)
                    latencies.append((time.perf_counter() - request_started) * 1000)
                except Exception as exc:
                    error_count += 1
                    if len(error_samples) < 20:
                        error_samples.append(f"{type(exc).__name__}: {exc}")

        tasks = [
            asyncio.create_task(worker(foreground_path, foreground_latencies))
            for _ in range(foreground_concurrency)
        ]
        tasks.extend(
            asyncio.create_task(worker(background_path, background_latencies))
            for _ in range(background_concurrency)
        )
        lane_started = loop.time()
        started.set()
        await asyncio.gather(*tasks)
        elapsed = loop.time() - lane_started

    return summarize_lane(
        elapsed=elapsed,
        foreground_latencies_ms=foreground_latencies,
        background_latencies_ms=background_latencies,
        error_count=error_count,
        error_samples=error_samples,
    )


async def benchmark(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    runs: dict[str, list[dict[str, Any]]] = {"control": [], "candidate": []}
    targets = {"control": args.control_url, "candidate": args.candidate_url}

    if args.warmup_seconds:
        for target in ("control", "candidate"):
            await run_lane(
                base_url=targets[target],
                foreground_path=args.foreground_path,
                background_path=args.background_path,
                foreground_concurrency=min(8, args.foreground_concurrency),
                background_concurrency=min(2, args.background_concurrency),
                duration_seconds=args.warmup_seconds,
                payload=payload,
                dimensions=args.dimensions,
            )

    for round_index in range(args.rounds):
        order = ("control", "candidate") if round_index % 2 == 0 else ("candidate", "control")
        for target in order:
            print(f"round {round_index + 1}/{args.rounds}: {target}", flush=True)
            result = await run_lane(
                base_url=targets[target],
                foreground_path=args.foreground_path,
                background_path=args.background_path,
                foreground_concurrency=args.foreground_concurrency,
                background_concurrency=args.background_concurrency,
                duration_seconds=args.duration_seconds,
                payload=payload,
                dimensions=args.dimensions,
            )
            result["round"] = round_index + 1
            result["position"] = order.index(target) + 1
            runs[target].append(result)

    return {
        "schema_version": 1,
        "protocol": {
            "foreground_concurrency": args.foreground_concurrency,
            "background_concurrency": args.background_concurrency,
            "total_concurrency": args.foreground_concurrency + args.background_concurrency,
            "duration_seconds": args.duration_seconds,
            "rounds": args.rounds,
            "order": "alternating control/candidate",
            "persistent_connections": True,
            "foreground_path": args.foreground_path,
            "background_path": args.background_path,
            "dimensions": args.dimensions,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "provenance": {
            "control": args.control_provenance,
            "candidate": args.candidate_provenance,
        },
        "runs": runs,
        "comparison": compare_runs(
            runs["control"],
            runs["candidate"],
            max_regression_percent=args.max_regression_percent,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--foreground-path", default="/v1/embeddings")
    parser.add_argument("--background-path", default="/v1/codedb/embeddings")
    parser.add_argument("--foreground-concurrency", type=int, default=256)
    parser.add_argument("--background-concurrency", type=int, default=32)
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--warmup-seconds", type=float, default=2.0)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--dimensions", type=int, default=512)
    parser.add_argument("--max-regression-percent", type=float, default=10.0)
    parser.add_argument("--payload-file", type=pathlib.Path)
    parser.add_argument("--control-provenance", default="unspecified")
    parser.add_argument("--candidate-provenance", default="unspecified")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("--rounds must be at least 2 so request order is reversed")
    if args.foreground_concurrency < 1 or args.background_concurrency < 1:
        parser.error("both concurrency values must be positive")
    return args


def main() -> None:
    args = parse_args()
    payload = (
        json.loads(args.payload_file.read_text())
        if args.payload_file
        else {
            "input": ["query: locate the request batching implementation"],
            "dimensions": args.dimensions,
        }
    )
    result = asyncio.run(benchmark(args, payload))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{rendered}\n")
    print(rendered)
    if not result["comparison"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
