#!/usr/bin/env python3
"""
Run the pgbench Docker suite multiple times from a clean state and report medians.

This is meant to produce publication-grade benchmark artifacts:
- each run starts from `docker compose down -v`
- raw stdout/stderr is saved per run
- medians are computed per query/driver over successful runs only
- failures are surfaced explicitly instead of being folded into prose
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = ROOT / "docker-compose.yml"
EXPECTED_QUERIES = {
    "7-oneplusone",
    "1-pg_type",
    "2-generate_series",
    "3-large_object",
    "4-arrays",
    "5-copyfrom",
    "6-batch",
}

QUERY_RE = re.compile(r"^pgbench-1\s+\|\s+=== Query: (?P<query>.+) ===$")
DRIVER_RE = re.compile(r"^pgbench-1\s+\|\s+--- (?P<driver>.+) \(concurrency=10, duration=30s\) ---$")
QPS_RE = re.compile(r"^pgbench-1\s+\|\s+Queries/sec:\s+(?P<value>[\d,]+)$")
RPS_RE = re.compile(r"^pgbench-1\s+\|\s+Rows/sec:\s+(?P<value>[\d,]+)$")
LAT_RE = re.compile(
    r"^pgbench-1\s+\|\s+Latency:\s+min=(?P<min>[\d.]+)ms\s+mean=(?P<mean>[\d.]+)ms\s+max=(?P<max>[\d.]+)ms$"
)


@dataclass
class Metric:
    queries_per_sec: float | None = None
    rows_per_sec: float | None = None
    mean_latency_ms: float | None = None
    status: str = "ok"
    error: str | None = None


def run_cmd(args: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture,
    )


def docker_compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run_cmd(["docker", "compose", "-f", str(COMPOSE_FILE), *args], cwd=ROOT.parent.parent, capture=capture)


def parse_log(text: str) -> dict[str, dict[str, Metric]]:
    results: dict[str, dict[str, Metric]] = {}
    current_query: str | None = None
    current_driver: str | None = None
    pending_error: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        query_match = QUERY_RE.match(line)
        if query_match:
            current_query = query_match.group("query")
            results.setdefault(current_query, {})
            current_driver = None
            pending_error = []
            continue

        driver_match = DRIVER_RE.match(line)
        if driver_match and current_query:
            current_driver = driver_match.group("driver")
            results[current_query][current_driver] = Metric()
            pending_error = []
            continue

        if not current_query or not current_driver:
            continue

        metric = results[current_query][current_driver]
        if "FAILED" in line:
            metric.status = "failed"
            pending_error = []
            continue

        qps_match = QPS_RE.match(line)
        if qps_match:
            metric.queries_per_sec = float(qps_match.group("value").replace(",", ""))
            continue

        rps_match = RPS_RE.match(line)
        if rps_match:
            metric.rows_per_sec = float(rps_match.group("value").replace(",", ""))
            continue

        lat_match = LAT_RE.match(line)
        if lat_match:
            metric.mean_latency_ms = float(lat_match.group("mean"))
            continue

        if metric.status == "failed" and line.startswith("pgbench-1  |"):
            content = line.split("|", 1)[1].strip()
            if content and content != "FAILED":
                pending_error.append(content)
                if "HINT:" in content or "Traceback" in content:
                    continue
                metric.error = " ".join(pending_error[-4:])

    return results


def validate_run_output(
    run_idx: int,
    up: subprocess.CompletedProcess[str],
    parsed: dict[str, dict[str, Metric]],
    log_path: Path,
) -> None:
    if up.returncode != 0:
        raise RuntimeError(
            f"run {run_idx} failed with exit code {up.returncode}; see {log_path}"
        )
    if not parsed:
        raise RuntimeError(f"run {run_idx} produced no parsed benchmark results; see {log_path}")
    missing_queries = sorted(EXPECTED_QUERIES - set(parsed))
    if missing_queries:
        raise RuntimeError(
            f"run {run_idx} is missing expected queries {missing_queries}; see {log_path}"
        )


def summarize(runs: list[dict[str, dict[str, Metric]]]) -> dict[str, dict[str, dict[str, float | int | str | None]]]:
    queries = sorted({query for run in runs for query in run})
    drivers = sorted({driver for run in runs for data in run.values() for driver in data})
    summary: dict[str, dict[str, dict[str, float | int | str | None]]] = {}

    for query in queries:
        summary[query] = {}
        for driver in drivers:
            samples = [run.get(query, {}).get(driver) for run in runs]
            successful = [sample for sample in samples if sample and sample.status == "ok" and sample.queries_per_sec is not None]
            failures = [sample for sample in samples if sample and sample.status != "ok"]

            if successful:
                summary[query][driver] = {
                    "status": "ok",
                    "successful_runs": len(successful),
                    "failed_runs": len(failures),
                    "median_qps": statistics.median(sample.queries_per_sec for sample in successful),
                    "median_rps": statistics.median(sample.rows_per_sec for sample in successful if sample.rows_per_sec is not None),
                    "median_latency_ms": statistics.median(
                        sample.mean_latency_ms for sample in successful if sample.mean_latency_ms is not None
                    ),
                    "min_qps": min(sample.queries_per_sec for sample in successful),
                    "max_qps": max(sample.queries_per_sec for sample in successful),
                }
            else:
                error = next((sample.error for sample in failures if sample and sample.error), None)
                summary[query][driver] = {
                    "status": "failed",
                    "successful_runs": 0,
                    "failed_runs": len(failures),
                    "median_qps": None,
                    "median_rps": None,
                    "median_latency_ms": None,
                    "min_qps": None,
                    "max_qps": None,
                    "error": error,
                }
    return summary


def format_number(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if digits == 0:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def print_markdown(summary: dict[str, dict[str, dict[str, float | int | str | None]]]) -> None:
    print("| Query | Driver | Median q/s | Median rows/s | Median mean latency | Success | Range |")
    print("|-------|--------|-----------:|--------------:|--------------------:|--------:|-------|")
    for query, drivers in summary.items():
        for driver, item in drivers.items():
            if item["status"] == "ok":
                success = f"{item['successful_runs']}/{item['successful_runs'] + item['failed_runs']}"
                qps_range = f"{format_number(item['min_qps'])}..{format_number(item['max_qps'])}"
                print(
                    f"| {query} | {driver} | {format_number(item['median_qps'])} | "
                    f"{format_number(item['median_rps'])} | {format_number(item['median_latency_ms'], 3)}ms | "
                    f"{success} | {qps_range} |"
                )
            else:
                print(
                    f"| {query} | {driver} | failed | failed | failed | 0/{item['failed_runs']} | "
                    f"{item.get('error') or 'see raw log'} |"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pgbench multiple times and report medians.")
    parser.add_argument("--runs", type=int, default=3, help="number of clean reruns to execute")
    parser.add_argument(
        "--artifacts-dir",
        default=str(ROOT / "artifacts"),
        help="directory for raw run logs and summary.json",
    )
    parser.add_argument("--skip-build", action="store_true", help="reuse existing images and skip --build")
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    all_runs: list[dict[str, dict[str, Metric]]] = []

    for run_idx in range(1, args.runs + 1):
        print(f"[run {run_idx}/{args.runs}] resetting docker state", file=sys.stderr)
        down = docker_compose("down", "-v", "--remove-orphans", capture=True)

        print(f"[run {run_idx}/{args.runs}] executing benchmark suite", file=sys.stderr)
        up_args = ["up"]
        if not args.skip_build:
            up_args.append("--build")
        up_args.extend(["--abort-on-container-exit", "pgbench"])
        up = docker_compose(*up_args, capture=True)

        run_log = "\n".join(
            [
                f"$ docker compose -f {COMPOSE_FILE} down -v --remove-orphans",
                down.stdout,
                down.stderr,
                f"$ docker compose -f {COMPOSE_FILE} {' '.join(up_args)}",
                up.stdout,
                up.stderr,
            ]
        )
        log_path = artifacts_dir / f"run-{run_idx:02d}.log"
        log_path.write_text(run_log)

        parsed = parse_log(up.stdout + "\n" + up.stderr)
        validate_run_output(run_idx, up, parsed, log_path)
        all_runs.append(parsed)

    summary = summarize(all_runs)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": args.runs,
        "artifacts_dir": str(artifacts_dir),
        "summary": summary,
        "raw_runs": [
            {
                query: {driver: asdict(metric) for driver, metric in drivers.items()}
                for query, drivers in run.items()
            }
            for run in all_runs
        ],
    }
    (artifacts_dir / "summary.json").write_text(json.dumps(payload, indent=2))

    print_markdown(summary)
    print(f"\nArtifacts written to {artifacts_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
